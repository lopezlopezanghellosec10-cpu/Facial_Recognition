/* Página de registro de la pluma.
 *
 * Habla con la API de web/main.py (misma dirección, por eso las rutas empiezan con "/"):
 *   POST /registro                      -> crea el registro y devuelve { persona_id, token }
 *   POST /registro/{id}/rostro          -> sube UNA foto (angulo + foto), header X-Token
 *   GET  /registro/{id}/estado          -> { estado, motivo, faltan }, header X-Token
 *
 * El token se muestra una sola vez, así que lo guardamos en este navegador
 * (localStorage) para poder retomar el registro si la persona cierra la página.
 */
(() => {
    'use strict';

    // ------------------------------------------------------------ constantes
    const ANGULOS = ['frente', 'izquierda', 'derecha'];
    const POSES = {
        frente: {
            nombre: 'Frente',
            guia: 'Mira de frente a la cámara, con la cara centrada y sin gorra.',
            giro: null,
        },
        izquierda: {
            nombre: 'Izquierda',
            guia: 'Gira la cabeza un poco hacia tu izquierda, sin dejar de ver la cámara.',
            giro: 'izquierda',
        },
        derecha: {
            nombre: 'Derecha',
            guia: 'Ahora gira la cabeza un poco hacia tu derecha.',
            giro: 'derecha',
        },
    };
    const CLAVE_REGISTRO = 'pluma_registro';
    const CLAVE_TEMA = 'pluma_tema';
    const LADO_MAXIMO = 1280;       // las fotos grandes se reducen antes de subirlas
    const SEGUNDOS_SONDEO = 15;     // cada cuánto revisamos si ya aprobaron el registro
    const RAZON_CAMPO = /^(nombre|telefono|correo)$/;

    // ---------------------------------------------------------------- estado
    const s = {
        id: null,
        token: null,
        nombre: '',
        correo: '',
        vista: 'datos',          // 'datos' | 'fotos' | 'estado'
        estado: 'pendiente',     // estado del registro en el servidor
        faltan: [...ANGULOS],    // ángulos que todavía no se han subido
        actual: 'frente',        // ángulo que se está tomando
        miniaturas: {},          // ángulo -> URL temporal de la foto subida
        ocupado: false,
        flujo: null,             // cámara abierta (MediaStream)
        sondeo: null,
    };

    const $ = (id) => document.getElementById(id);
    const el = {
        escena: $('escena'), estadoPluma: $('estado-pluma'), pasos: $('pasos'),
        cargando: $('cargando'), anuncio: $('anuncio'), btnTema: $('btn-tema'),
        secciones: { datos: $('paso-datos'), fotos: $('paso-fotos'), estado: $('paso-estado') },
        titulos: { datos: $('t-datos'), fotos: $('t-fotos'), estado: $('t-estado') },
        form: $('form-datos'), btnDatos: $('btn-datos'), avisoDatos: $('aviso-datos'),
        campos: { nombre: $('nombre'), telefono: $('telefono'), correo: $('correo'), acepto: $('acepto') },
        errores: {
            nombre: $('err-nombre'), telefono: $('err-telefono'),
            correo: $('err-correo'), acepto: $('err-acepto'),
        },
        guia: $('guia-pose'), visor: $('visor'), video: $('video'), giro: $('giro'),
        cuenta: $('cuenta'), analizando: $('analizando'),
        sinCamara: $('sin-camara'), msgCamara: $('msg-camara'),
        poses: $('poses'), avisoFotos: $('aviso-fotos'),
        btnFoto: $('btn-foto'), btnArchivo: $('btn-archivo'), archivo: $('archivo'),
        estadoTexto: $('estado-texto'), estadoMotivo: $('estado-motivo'),
        btnReintentar: $('btn-reintentar'),
    };

    // ------------------------------------------------------- almacenamiento
    // localStorage puede fallar (modo privado, datos bloqueados): siempre con try/catch.
    function leer(clave) {
        try { return localStorage.getItem(clave); } catch { return null; }
    }
    function escribir(clave, valor) {
        try { localStorage.setItem(clave, valor); } catch { /* sin almacenamiento: no pasa nada */ }
    }
    function borrar(clave) {
        try { localStorage.removeItem(clave); } catch { /* idem */ }
    }
    function guardarRegistro() {
        escribir(CLAVE_REGISTRO, JSON.stringify({
            id: s.id, token: s.token, nombre: s.nombre, correo: s.correo,
        }));
    }
    function leerRegistro() {
        try { return JSON.parse(leer(CLAVE_REGISTRO) || 'null'); } catch { return null; }
    }

    // ------------------------------------------------------------------ red
    async function llamar(ruta, opciones) {
        try {
            const respuesta = await fetch(ruta, opciones);
            let data = null;
            try { data = await respuesta.json(); } catch { /* respuesta sin JSON */ }
            return { ok: respuesta.ok, status: respuesta.status, data };
        } catch {
            return { ok: false, status: 0, data: null };   // sin conexión
        }
    }

    function textoError(res) {
        if (res.status === 0) return 'No hay conexión con el servidor. Revisa tu internet e intenta de nuevo.';
        if (res.status === 429) return 'Hiciste muchos intentos seguidos. Espera unos minutos e intenta de nuevo.';
        if (res.status === 503) return 'El sistema no está disponible por ahora. Intenta en unos minutos.';
        const detalle = res.data && res.data.detail;
        if (typeof detalle === 'string') return detalle;
        if (Array.isArray(detalle)) {
            // Errores de validación de FastAPI: [{ loc: [...], msg: "Value error, ..." }]
            return detalle
                .map((e) => String(e.msg || '').replace(/^Value error,\s*/, ''))
                .filter(Boolean)
                .join(' ');
        }
        return 'Algo salió mal. Intenta de nuevo.';
    }

    // ----------------------------------------------------------- utilidades
    const esperar = (ms) => new Promise((ok) => setTimeout(ok, ms));
    const soloDigitos = (t) => t.replace(/\D/g, '');

    function anunciar(texto) {
        el.anuncio.textContent = '';
        // pequeño retraso para que el lector de pantalla note el cambio
        setTimeout(() => { el.anuncio.textContent = texto; }, 50);
    }

    function formatearTelefono(valor) {
        let d = soloDigitos(valor);
        if (d.length >= 12 && d.startsWith('52')) d = d.slice(2);   // quita la lada de México si la pegan
        d = d.slice(0, 10);
        const partes = [d.slice(0, 3), d.slice(3, 6), d.slice(6, 10)].filter(Boolean);
        return partes.join(' ');
    }

    function mostrarAviso(nodo, texto) { nodo.textContent = texto; }

    // ---------------------------------------------------- la pluma (escena)
    function actualizarPluma() {
        let fase, grados, texto;
        if (s.vista === 'datos') {
            fase = 'datos'; grados = 0; texto = 'La pluma está cerrada.';
        } else if (s.vista === 'fotos') {
            const listas = ANGULOS.length - s.faltan.length;
            fase = 'fotos';
            grados = -8 - listas * 9;
            texto = listas === 0 ? 'Faltan tus tres fotos.' : `Llevas ${listas} de 3 fotos.`;
        } else if (s.estado === 'aprobado') {
            fase = 'aprobado'; grados = -74; texto = 'Aprobado: la pluma está abierta para ti.';
        } else if (s.estado === 'rechazado') {
            fase = 'rechazado'; grados = 0; texto = 'Sin acceso por ahora.';
        } else {
            fase = 'revision'; grados = -34; texto = 'En revisión.';
        }
        el.escena.dataset.fase = fase;
        el.escena.style.setProperty('--giro', `${grados}deg`);
        el.estadoPluma.textContent = texto;
    }

    // ------------------------------------------------------------ navegación
    function mostrar(vista) {
        const anterior = s.vista;
        s.vista = vista;
        el.cargando.hidden = true;

        for (const [nombre, seccion] of Object.entries(el.secciones)) {
            seccion.hidden = nombre !== vista;
        }

        // indicador de pasos
        const orden = ['datos', 'fotos', 'estado'];
        el.pasos.querySelectorAll('li').forEach((li) => {
            const i = orden.indexOf(li.dataset.vista);
            const actual = orden.indexOf(vista);
            li.classList.toggle('activo', i === actual);
            li.classList.toggle('hecho', i < actual || (vista === 'estado' && s.estado === 'aprobado'));
            if (i === actual) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
        });

        detenerSondeo();
        if (vista === 'fotos') {
            prepararFotos();
            iniciarCamara();
        } else {
            detenerCamara();
        }
        if (vista === 'estado') {
            pintarEstado();
            if (s.estado === 'pendiente') iniciarSondeo();
        }

        actualizarPluma();
        if (anterior !== vista) el.titulos[vista].focus({ preventScroll: false });
    }

    // ----------------------------------------------------- paso 1: formulario
    function validar() {
        const errores = {};
        const nombre = el.campos.nombre.value.trim().replace(/\s+/g, ' ');
        if (nombre.length < 5 || !nombre.includes(' ')) {
            errores.nombre = 'Escribe tu nombre completo, con nombre y apellido.';
        }
        const telefono = soloDigitos(el.campos.telefono.value);
        if (telefono.length !== 10) {
            errores.telefono = 'El teléfono debe tener 10 dígitos.';
        }
        const correo = el.campos.correo.value.trim().toLowerCase();
        if (!/^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(correo)) {
            errores.correo = 'Escribe un correo válido, por ejemplo nombre@gmail.com.';
        }
        // Solo se pide aceptar el aviso de las fotos; no se manda al servidor.
        if (!el.campos.acepto.checked) {
            errores.acepto = 'Para continuar, acepta el uso de tus fotos.';
        }
        return { errores, valores: { nombre, telefono, correo } };
    }

    function pintarErrores(errores) {
        for (const campo of Object.keys(el.campos)) {
            const mensaje = errores[campo] || '';
            el.errores[campo].textContent = mensaje;
            if (mensaje) el.campos[campo].setAttribute('aria-invalid', 'true');
            else el.campos[campo].removeAttribute('aria-invalid');
        }
    }

    async function enviarDatos(evento) {
        evento.preventDefault();
        mostrarAviso(el.avisoDatos, '');
        const { errores, valores } = validar();
        pintarErrores(errores);
        const primero = Object.keys(errores)[0];
        if (primero) { el.campos[primero].focus(); return; }

        el.btnDatos.disabled = true;
        el.btnDatos.textContent = 'Creando tu registro…';
        const res = await llamar('/registro', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(valores),
        });
        el.btnDatos.disabled = false;
        el.btnDatos.textContent = 'Continuar';

        if (!res.ok) {
            if (res.status === 409) {
                pintarErrores({ correo: 'Ese correo ya tiene un registro. Usa otro correo.' });
                el.campos.correo.focus();
            } else if (res.status === 422 && Array.isArray(res.data && res.data.detail)) {
                // Mostramos cada error de validación bajo su campo.
                const porCampo = {};
                for (const e of res.data.detail) {
                    const campo = (e.loc || [])[e.loc.length - 1];
                    if (RAZON_CAMPO.test(campo)) {
                        porCampo[campo] = String(e.msg || '').replace(/^Value error,\s*/, '');
                    }
                }
                if (Object.keys(porCampo).length) pintarErrores(porCampo);
                else mostrarAviso(el.avisoDatos, textoError(res));
            } else {
                mostrarAviso(el.avisoDatos, textoError(res));
            }
            return;
        }

        s.id = res.data.persona_id;
        s.token = res.data.token;
        s.nombre = valores.nombre;
        s.correo = valores.correo;
        s.estado = 'pendiente';
        s.faltan = [...ANGULOS];
        s.actual = ANGULOS[0];
        guardarRegistro();
        mostrar('fotos');
    }

    // ------------------------------------------------------ paso 2: las fotos
    function prepararFotos() {
        mostrarAviso(el.avisoFotos, '');
        pintarPoses();
        elegirPose(s.faltan[0] || ANGULOS[0]);
    }

    function pintarPoses() {
        el.poses.textContent = '';
        for (const angulo of ANGULOS) {
            const lista = !s.faltan.includes(angulo);
            const li = document.createElement('li');
            const boton = document.createElement('button');
            boton.type = 'button';
            boton.className = 'pose' + (lista ? ' lista' : '') + (angulo === s.actual ? ' activa' : '');
            boton.dataset.angulo = angulo;
            boton.setAttribute('aria-pressed', angulo === s.actual ? 'true' : 'false');

            if (s.miniaturas[angulo]) {
                const img = document.createElement('img');
                img.src = s.miniaturas[angulo];
                img.alt = '';
                boton.append(img);
            }
            const texto = document.createElement('span');
            const nombre = document.createElement('strong');
            nombre.textContent = POSES[angulo].nombre;
            const estado = document.createElement('small');
            estado.textContent = lista ? 'Lista' : angulo === s.actual ? 'Ahora' : 'Pendiente';
            texto.append(nombre, estado);
            boton.append(texto);

            li.append(boton);
            el.poses.append(li);
        }
    }

    function elegirPose(angulo) {
        s.actual = angulo;
        el.guia.textContent = `${POSES[angulo].nombre}: ${POSES[angulo].guia}`;
        const lado = POSES[angulo].giro;
        el.giro.hidden = !lado;
        if (lado) el.giro.dataset.lado = lado;
        pintarPoses();
        anunciar(POSES[angulo].guia);
    }

    function ocupar(valor, mensaje) {
        s.ocupado = valor;
        el.btnFoto.disabled = valor;
        el.btnArchivo.disabled = valor;
        el.analizando.hidden = !valor;
        if (mensaje) el.analizando.querySelector('span').textContent = mensaje;
    }

    // --- cámara
    async function iniciarCamara() {
        detenerCamara();
        el.sinCamara.hidden = true;
        el.video.hidden = false;
        el.btnFoto.hidden = false;

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            return camaraNoDisponible(
                'Este navegador no puede abrir la cámara en esta dirección (necesita https o localhost). Sube una foto.'
            );
        }
        try {
            s.flujo = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 960 } },
                audio: false,
            });
            if (s.vista !== 'fotos') { detenerCamara(); return; }   // se fue de la página mientras pedía permiso
            el.video.srcObject = s.flujo;
            await el.video.play();
        } catch (error) {
            const negado = error && (error.name === 'NotAllowedError' || error.name === 'SecurityError');
            camaraNoDisponible(negado
                ? 'No diste permiso para usar la cámara. Actívalo en el navegador o sube una foto.'
                : 'No encontramos una cámara. Sube una foto.');
        }
    }

    function camaraNoDisponible(mensaje) {
        detenerCamara();
        el.msgCamara.textContent = mensaje;
        el.sinCamara.hidden = false;
        el.btnFoto.hidden = true;
    }

    function detenerCamara() {
        if (s.flujo) s.flujo.getTracks().forEach((pista) => pista.stop());
        s.flujo = null;
        el.video.srcObject = null;
    }

    async function cuentaRegresiva(segundos) {
        for (let i = segundos; i > 0; i--) {
            el.cuenta.textContent = i;
            el.cuenta.classList.add('visible');
            await esperar(850);
        }
        el.cuenta.classList.remove('visible');
        el.cuenta.textContent = '';
    }

    function capturarCuadro() {
        const ancho = el.video.videoWidth;
        const alto = el.video.videoHeight;
        if (!ancho || !alto) return Promise.reject(new Error('La cámara todavía no está lista.'));
        const escala = Math.min(1, LADO_MAXIMO / Math.max(ancho, alto));
        const lienzo = document.createElement('canvas');
        lienzo.width = Math.round(ancho * escala);
        lienzo.height = Math.round(alto * escala);
        lienzo.getContext('2d').drawImage(el.video, 0, 0, lienzo.width, lienzo.height);
        return new Promise((ok, fallo) => {
            lienzo.toBlob((b) => (b ? ok(b) : fallo(new Error('No se pudo guardar la foto.'))), 'image/jpeg', 0.92);
        });
    }

    async function tomarFoto() {
        if (s.ocupado) return;
        mostrarAviso(el.avisoFotos, '');
        el.btnFoto.disabled = true;
        el.btnArchivo.disabled = true;
        await cuentaRegresiva(3);
        let foto;
        try {
            foto = await capturarCuadro();
        } catch (error) {
            el.btnFoto.disabled = false;
            el.btnArchivo.disabled = false;
            mostrarAviso(el.avisoFotos, error.message);
            return;
        }
        enviarFoto(foto);
    }

    // Reduce y convierte a JPG las fotos que la persona sube desde su galería
    // (las de celular pesan mucho y el servidor rechaza las de más de 5 MB).
    async function prepararArchivo(archivo) {
        try {
            const imagen = await createImageBitmap(archivo);   // respeta la rotación de la foto
            const escala = Math.min(1, LADO_MAXIMO / Math.max(imagen.width, imagen.height));
            const lienzo = document.createElement('canvas');
            lienzo.width = Math.round(imagen.width * escala);
            lienzo.height = Math.round(imagen.height * escala);
            lienzo.getContext('2d').drawImage(imagen, 0, 0, lienzo.width, lienzo.height);
            if (imagen.close) imagen.close();
            return await new Promise((ok, fallo) => {
                lienzo.toBlob((b) => (b ? ok(b) : fallo(new Error('toBlob'))), 'image/jpeg', 0.92);
            });
        } catch {
            return archivo;   // si el navegador no puede, mandamos el original
        }
    }

    async function enviarFoto(foto) {
        const angulo = s.actual;
        ocupar(true, 'Revisando tu foto…');

        const formulario = new FormData();
        formulario.append('angulo', angulo);
        formulario.append('foto', foto, `${angulo}.jpg`);

        const res = await llamar(`/registro/${s.id}/rostro`, {
            method: 'POST',
            headers: { 'X-Token': s.token },
            body: formulario,
        });
        ocupar(false);

        if (!res.ok) {
            if (res.status === 403) return registroCerrado();
            mostrarAviso(el.avisoFotos, textoError(res));
            anunciar(textoError(res));
            return;
        }

        if (s.miniaturas[angulo]) URL.revokeObjectURL(s.miniaturas[angulo]);
        s.miniaturas[angulo] = URL.createObjectURL(foto);
        s.faltan = res.data.faltan;

        if (res.data.completo) {
            s.estado = 'pendiente';
            mostrar('estado');
        } else {
            elegirPose(s.faltan[0]);
            actualizarPluma();
        }
    }

    function registroCerrado() {
        // 403: el token no sirve o el registro ya no está abierto. Lo más sano es revisar el estado real.
        refrescarEstado(true);
    }

    // ---------------------------------------------------- paso 3: el estado
    function pintarEstado() {
        const titulo = el.titulos.estado;
        el.estadoMotivo.hidden = true;
        el.btnReintentar.hidden = true;

        if (s.estado === 'aprobado') {
            titulo.textContent = 'Tu registro fue aprobado';
            el.estadoTexto.textContent =
                (s.nombre ? `${s.nombre}, ya` : 'Ya') + ' puedes usar el acceso automático de la pluma.';
        } else if (s.estado === 'rechazado') {
            titulo.textContent = 'Tu registro no está activo';
            el.estadoTexto.textContent = 'El administrador dejó este mensaje:';
            el.estadoMotivo.textContent = s.motivo || 'Sin motivo indicado.';
            el.estadoMotivo.hidden = false;
            el.btnReintentar.hidden = false;
        } else {
            titulo.textContent = 'Tu registro está en revisión';
            el.estadoTexto.textContent =
                'El administrador va a revisar tus datos y tus fotos.' +
                (s.correo ? ` Te avisaremos por correo a ${s.correo}.` : ' Te avisaremos por correo.') +
                ' Puedes cerrar esta página y volver después: aquí verás el resultado.';
        }
    }

    function iniciarSondeo() {
        detenerSondeo();
        s.sondeo = setInterval(() => refrescarEstado(false), SEGUNDOS_SONDEO * 1000);
    }
    function detenerSondeo() {
        if (s.sondeo) clearInterval(s.sondeo);
        s.sondeo = null;
    }

    async function refrescarEstado(forzarVista) {
        const res = await llamar(`/registro/${s.id}/estado`, { headers: { 'X-Token': s.token } });
        if (!res.ok) {
            if (res.status === 403 || res.status === 404) {
                borrar(CLAVE_REGISTRO);
                reiniciar('Tu registro anterior ya no está disponible. Empieza de nuevo.');
            } else if (forzarVista) {
                mostrarAviso(el.avisoFotos, textoError(res));
            }
            return;
        }
        aplicarEstadoDelServidor(res.data, forzarVista);
    }

    function aplicarEstadoDelServidor(datos, forzarVista) {
        const cambio = s.estado !== datos.estado;
        s.estado = datos.estado;
        s.motivo = datos.motivo;
        s.faltan = datos.faltan;

        if (datos.estado === 'pendiente' && datos.faltan.length > 0) {
            if (s.vista !== 'fotos' || forzarVista) { s.actual = datos.faltan[0]; mostrar('fotos'); }
            return;
        }
        if (s.vista !== 'estado' || cambio || forzarVista) {
            mostrar('estado');
            if (cambio) anunciar(el.titulos.estado.textContent);
        }
    }

    function reiniciar(aviso) {
        detenerSondeo();
        s.id = null; s.token = null; s.estado = 'pendiente'; s.motivo = '';
        s.faltan = [...ANGULOS]; s.actual = ANGULOS[0];
        Object.values(s.miniaturas).forEach((u) => URL.revokeObjectURL(u));
        s.miniaturas = {};
        mostrar('datos');
        mostrarAviso(el.avisoDatos, aviso || '');
    }

    function volverARegistrarse() {
        const nombre = s.nombre;
        const correo = s.correo;
        borrar(CLAVE_REGISTRO);
        reiniciar('');
        el.campos.nombre.value = nombre || '';
        el.campos.correo.value = correo || '';
        el.campos.telefono.focus();
    }

    // ---------------------------------------------------------------- tema
    function aplicarTema(tema) {
        document.documentElement.dataset.theme = tema;
        el.btnTema.textContent = tema === 'claro' ? 'Tema oscuro' : 'Tema claro';
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.content = tema === 'claro' ? '#e3e7ee' : '#1b2130';
    }

    // -------------------------------------------------------------- eventos
    function conectarEventos() {
        el.btnTema.addEventListener('click', () => {
            const nuevo = document.documentElement.dataset.theme === 'claro' ? 'oscuro' : 'claro';
            aplicarTema(nuevo);
            escribir(CLAVE_TEMA, nuevo);
        });

        el.form.addEventListener('submit', enviarDatos);
        el.campos.telefono.addEventListener('input', () => {
            el.campos.telefono.value = formatearTelefono(el.campos.telefono.value);
        });
        for (const campo of Object.keys(el.campos)) {
            el.campos[campo].addEventListener('input', () => {
                el.errores[campo].textContent = '';
                el.campos[campo].removeAttribute('aria-invalid');
            });
        }

        el.btnFoto.addEventListener('click', tomarFoto);
        el.btnArchivo.addEventListener('click', () => { if (!s.ocupado) el.archivo.click(); });
        el.archivo.addEventListener('change', async () => {
            const archivo = el.archivo.files && el.archivo.files[0];
            el.archivo.value = '';
            if (!archivo || s.ocupado) return;
            mostrarAviso(el.avisoFotos, '');
            ocupar(true, 'Preparando tu foto…');
            const listo = await prepararArchivo(archivo);
            ocupar(false);
            enviarFoto(listo);
        });

        el.poses.addEventListener('click', (e) => {
            const boton = e.target.closest('.pose');
            if (boton && !s.ocupado) elegirPose(boton.dataset.angulo);
        });

        el.btnReintentar.addEventListener('click', volverARegistrarse);

        // Si la persona cambia de pestaña, apagamos la cámara; al volver la prendemos.
        document.addEventListener('visibilitychange', () => {
            if (s.vista !== 'fotos') return;
            if (document.hidden) detenerCamara(); else iniciarCamara();
        });
    }

    // --------------------------------------------------------------- inicio
    async function iniciar() {
        aplicarTema(document.documentElement.dataset.theme === 'claro' ? 'claro' : 'oscuro');
        conectarEventos();

        const guardado = leerRegistro();
        if (guardado && guardado.id && guardado.token) {
            s.id = guardado.id;
            s.token = guardado.token;
            s.nombre = guardado.nombre || '';
            s.correo = guardado.correo || '';

            const res = await llamar(`/registro/${s.id}/estado`, { headers: { 'X-Token': s.token } });
            if (res.ok) { aplicarEstadoDelServidor(res.data, true); return; }
            if (res.status === 403 || res.status === 404) {
                borrar(CLAVE_REGISTRO);
                s.id = null; s.token = null;
            } else {
                // Sin conexión o servidor caído: no perdemos el registro guardado.
                mostrar('datos');
                mostrarAviso(el.avisoDatos, 'No pudimos revisar tu registro guardado. ' + textoError(res));
                return;
            }
        }
        mostrar('datos');
    }

    iniciar();
})();
