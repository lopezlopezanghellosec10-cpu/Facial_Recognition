/* Panel de la pluma (para el portero o administrador).
 *
 * Usa la API de web/admin.py. Todas las peticiones llevan la clave en el encabezado
 * X-Admin-Key:
 *   GET  /admin/resumen                     -> { pendiente, aprobado, rechazado }
 *   GET  /admin/personas?estado=pendiente   -> lista de personas
 *   GET  /admin/personas/{id}               -> una persona + parecidos + fotos_disponibles
 *   GET  /admin/personas/{id}/foto/{angulo} -> la foto (imagen)
 *   POST /admin/personas/{id}/aprobar
 *   POST /admin/personas/{id}/rechazar      { motivo }
 *   POST /admin/personas/{id}/revocar       { motivo }
 *
 * Las fotos NO se pueden poner directo en <img src="...">, porque una imagen no puede
 * mandar la clave. Por eso se piden con fetch, se convierten en una URL temporal
 * (blob) y esa URL es la que se muestra.
 *
 * La clave se guarda en sessionStorage: se borra sola al cerrar la pestaña.
 */
(() => {
    'use strict';

    const CLAVE_SESION = 'pluma_admin_clave';
    const CLAVE_TEMA = 'pluma_tema';
    const SEGUNDOS_SONDEO = 20;
    const ANGULOS = ['frente', 'izquierda', 'derecha'];
    const ROTULO = {
        frente: 'Frente',
        izquierda: 'Giro a la izquierda',
        derecha: 'Giro a la derecha',
    };
    const ETIQUETA = { pendiente: 'Pendiente', aprobado: 'Aprobada', rechazado: 'Sin acceso' };
    const VACIO = {
        pendiente: 'No hay registros pendientes. Cuando alguien se registre, aparecerá aquí.',
        aprobado: 'Todavía no hay personas aprobadas.',
        rechazado: 'Nadie está sin acceso por ahora.',
    };
    const MOTIVOS_RAPIDOS = [
        'La foto salió borrosa. Vuelve a tomarla con más luz.',
        'No se ve tu rostro completo. Quita gorra o lentes y mira de frente.',
        'Las fotos no parecen ser de la misma persona.',
        'Faltan fotos. Vuelve a registrarte y sube las tres.',
    ];

    // ---------------------------------------------------------------- estado
    const s = {
        clave: '',
        entro: false,
        estado: 'pendiente',   // pestaña activa
        lista: [],
        cuentas: null,
        seleccionado: null,
        detalle: null,
        modo: 'inicio',        // inicio | aprobando | rechazando | revocando
        ocupado: false,
        cargando: false,       // true mientras llega la lista de una pestaña nueva
        urls: [],              // URLs temporales de fotos (se liberan al cambiar de persona)
        peticion: 0,           // para ignorar respuestas viejas
        sondeo: null,
    };

    const $ = (id) => document.getElementById(id);
    const el = {
        login: $('login'), formLogin: $('form-login'), clave: $('clave'),
        avisoLogin: $('aviso-login'), btnLogin: $('btn-login'),
        app: $('app'), cuerpo: $('cuerpo'), lista: $('lista'), listaVacia: $('lista-vacia'),
        detalleVacio: $('detalle-vacio'), persona: $('persona'), btnVolver: $('btn-volver'),
        nombre: $('p-nombre'), estado: $('p-estado'), hace: $('p-hace'),
        alertas: $('p-alertas'), fotos: $('p-fotos'), fotosNota: $('p-fotos-nota'),
        datos: $('p-datos'), decision: $('p-decision'),
        btnTema: $('btn-tema'), btnSalir: $('btn-salir'),
        visor: $('visor'), visorImg: $('visor-img'), visorCerrar: $('visor-cerrar'),
        avisos: $('avisos'),
        pestanas: [...document.querySelectorAll('.pestana')],
    };

    // --------------------------------------------------------------- utilidades
    /** Crea un elemento. Todo el texto entra con textContent, nunca como HTML. */
    function h(etiqueta, props = {}, ...hijos) {
        const nodo = document.createElement(etiqueta);
        for (const [clave, valor] of Object.entries(props)) {
            if (valor === null || valor === undefined || valor === false) continue;
            if (clave === 'class') nodo.className = valor;
            else if (clave === 'texto') nodo.textContent = valor;
            else if (clave.startsWith('on')) nodo.addEventListener(clave.slice(2), valor);
            else nodo.setAttribute(clave, valor === true ? '' : valor);
        }
        for (const hijo of hijos.flat()) {
            if (hijo === null || hijo === undefined || hijo === false) continue;
            nodo.append(hijo.nodeType ? hijo : document.createTextNode(String(hijo)));
        }
        return nodo;
    }

    function leer(clave, almacen = sessionStorage) {
        try { return almacen.getItem(clave); } catch { return null; }
    }
    function escribir(clave, valor, almacen = sessionStorage) {
        try { almacen.setItem(clave, valor); } catch { /* sin almacenamiento */ }
    }
    function borrar(clave, almacen = sessionStorage) {
        try { almacen.removeItem(clave); } catch { /* idem */ }
    }

    function haceTiempo(iso) {
        const fecha = new Date(iso);
        if (Number.isNaN(fecha.getTime())) return '';
        const minutos = Math.max(0, Math.floor((Date.now() - fecha.getTime()) / 60000));
        if (minutos < 1) return 'justo ahora';
        if (minutos < 60) return `hace ${minutos} min`;
        const horas = Math.floor(minutos / 60);
        if (horas < 24) return `hace ${horas} h`;
        const dias = Math.floor(horas / 24);
        return dias === 1 ? 'hace 1 día' : `hace ${dias} días`;
    }

    function fechaLarga(iso) {
        const fecha = new Date(iso);
        if (Number.isNaN(fecha.getTime())) return '';
        return fecha.toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' });
    }

    function formatearTelefono(t) {
        const d = String(t || '').replace(/\D/g, '');
        return d.length === 10 ? `${d.slice(0, 3)} ${d.slice(3, 6)} ${d.slice(6)}` : String(t || '');
    }

    function textoError(res) {
        if (res.status === 0) return 'No hay conexión con el servidor. Revisa que esté prendido.';
        const detalle = res.data && res.data.detail;
        if (typeof detalle === 'string') return detalle;
        if (Array.isArray(detalle)) {
            return detalle.map((e) => String(e.msg || '').replace(/^Value error,\s*/, '')).filter(Boolean).join(' ');
        }
        if (res.status === 503) return 'El sistema no está disponible por ahora.';
        return 'Algo salió mal. Intenta de nuevo.';
    }

    // ------------------------------------------------------------------ avisos
    function avisar(texto, tipo = 'ok', persistente = false) {
        const aviso = h('div', { class: `aviso-flotante ${tipo === 'error' ? 'error-aviso' : tipo === 'info' ? 'info-aviso' : ''}` },
            h('p', { texto }),
            h('button', { type: 'button', onclick: () => aviso.remove() }, 'Cerrar'));
        el.avisos.append(aviso);
        if (!persistente) setTimeout(() => aviso.remove(), 6000);
    }

    // --------------------------------------------------------------------- red
    async function api(ruta, { metodo = 'GET', cuerpo = null, blob = false } = {}) {
        const opciones = { method: metodo, headers: { 'X-Admin-Key': s.clave } };
        if (cuerpo) {
            opciones.headers['Content-Type'] = 'application/json';
            opciones.body = JSON.stringify(cuerpo);
        }
        try {
            const respuesta = await fetch(ruta, opciones);
            if (respuesta.status === 403 && s.entro) {
                cerrarSesion('La clave dejó de ser válida. Entra de nuevo.');
                return { ok: false, status: 403, data: null, sesion: true };
            }
            if (blob && respuesta.ok) return { ok: true, status: respuesta.status, data: await respuesta.blob() };
            let data = null;
            try { data = await respuesta.json(); } catch { /* sin JSON */ }
            return { ok: respuesta.ok, status: respuesta.status, data };
        } catch {
            return { ok: false, status: 0, data: null };
        }
    }

    // ----------------------------------------------------------------- sesión
    async function iniciarSesion(evento) {
        evento.preventDefault();
        el.avisoLogin.textContent = '';
        const clave = el.clave.value;
        if (!clave) { el.avisoLogin.textContent = 'Escribe la clave de administrador.'; el.clave.focus(); return; }

        el.btnLogin.disabled = true;
        s.clave = clave;
        const res = await api('/admin/resumen');
        el.btnLogin.disabled = false;

        if (!res.ok) {
            s.clave = '';
            el.avisoLogin.textContent = res.status === 403 ? 'Clave incorrecta.' : textoError(res);
            el.clave.select();
            return;
        }
        escribir(CLAVE_SESION, clave);
        el.clave.value = '';
        entrar(res.data);
    }

    function entrar(cuentas) {
        s.entro = true;
        el.login.hidden = true;
        el.app.hidden = false;
        pintarCuentas(cuentas, false);
        cargarLista().then(() => {
            // En pantalla grande abrimos de una vez al primero de la fila.
            if (s.lista.length && !esCelular()) seleccionar(s.lista[0].id);
        });
        detenerSondeo();
        s.sondeo = setInterval(refrescar, SEGUNDOS_SONDEO * 1000);
    }

    function cerrarSesion(mensaje) {
        detenerSondeo();
        liberarFotos();
        borrar(CLAVE_SESION);
        s.clave = ''; s.entro = false; s.lista = []; s.cuentas = null;
        s.seleccionado = null; s.detalle = null; s.estado = 'pendiente';
        el.app.hidden = true;
        el.login.hidden = false;
        el.persona.hidden = true;
        el.detalleVacio.hidden = false;
        document.title = 'Panel de la pluma';
        el.avisoLogin.textContent = mensaje || '';
        el.clave.focus();
    }

    function detenerSondeo() {
        if (s.sondeo) clearInterval(s.sondeo);
        s.sondeo = null;
    }

    const esCelular = () => window.matchMedia('(max-width: 860px)').matches;

    // ------------------------------------------------------------------ cuentas
    function pintarCuentas(cuentas, avisarNuevos = true) {
        const anterior = s.cuentas;
        s.cuentas = cuentas;
        for (const estado of ['pendiente', 'aprobado', 'rechazado']) {
            const nodo = $('c-' + estado);
            nodo.textContent = cuentas[estado] ?? 0;
            nodo.classList.toggle('hay', estado === 'pendiente' && cuentas.pendiente > 0);
        }
        document.title = cuentas.pendiente > 0 ? `(${cuentas.pendiente}) Panel de la pluma` : 'Panel de la pluma';
        if (avisarNuevos && anterior && cuentas.pendiente > anterior.pendiente) {
            const nuevos = cuentas.pendiente - anterior.pendiente;
            avisar(nuevos === 1 ? 'Llegó un registro nuevo.' : `Llegaron ${nuevos} registros nuevos.`, 'info');
        }
    }

    async function cargarCuentas() {
        const res = await api('/admin/resumen');
        if (res.ok) pintarCuentas(res.data);
    }

    // -------------------------------------------------------------------- lista
    async function cargarLista() {
        const estado = s.estado;
        const res = await api(`/admin/personas?estado=${estado}`);
        if (estado !== s.estado) return false;      // cambió de pestaña mientras cargaba
        s.cargando = false;
        if (!res.ok) {
            pintarLista();
            if (!res.sesion) avisar(textoError(res), 'error');
            return false;
        }
        s.lista = res.data;
        pintarLista();
        return true;
    }

    function textoVacio() { return s.cargando ? 'Cargando…' : VACIO[s.estado]; }

    function pintarLista() {
        el.lista.textContent = '';
        el.listaVacia.hidden = s.lista.length > 0;
        el.listaVacia.textContent = textoVacio();

        for (const persona of s.lista) {
            const activa = persona.id === s.seleccionado;
            const subidas = Object.values(persona.fotos || {}).filter(Boolean).length;
            const meta = [h('span', { texto: haceTiempo(persona.creada_en) })];
            if (s.estado === 'pendiente' && subidas < ANGULOS.length) {
                meta.push(h('span', { class: 'insignia', texto: `Fotos ${subidas} de 3` }));
            }
            el.lista.append(h('li', {},
                h('button', {
                    type: 'button',
                    class: 'fila' + (activa ? ' activa' : ''),
                    'aria-pressed': activa ? 'true' : 'false',
                    onclick: () => seleccionar(persona.id),
                },
                    h('span', { class: 'fila-nombre', texto: persona.nombre }),
                    h('span', { class: 'fila-meta' }, meta))));
        }
    }

    function cambiarPestana(estado) {
        if (estado === s.estado) { if (esCelular()) el.cuerpo.dataset.vista = 'lista'; return; }
        s.estado = estado;
        s.seleccionado = null;
        s.detalle = null;
        s.lista = [];
        s.cargando = true;          // mientras llega la lista nueva no se muestra la vieja
        s.peticion++;
        ocultarDetalle();
        pintarLista();
        el.pestanas.forEach((p) => p.setAttribute('aria-pressed', p.dataset.estado === estado ? 'true' : 'false'));
        cargarLista().then(() => {
            if (s.lista.length && !esCelular()) seleccionar(s.lista[0].id);
        });
        el.cuerpo.dataset.vista = 'lista';
    }

    async function refrescar() {
        if (!s.entro) return;
        await cargarCuentas();
        const antes = s.seleccionado;
        const bien = await cargarLista();
        if (bien && antes && !s.lista.some((p) => p.id === antes) && s.modo === 'inicio') {
            avisar('Esa persona ya fue revisada por alguien más.', 'info');
            s.seleccionado = null; s.detalle = null;
            ocultarDetalle();
            pintarLista();
        }
    }

    // ------------------------------------------------------------------ detalle
    function ocultarDetalle() {
        liberarFotos();
        el.persona.hidden = true;
        el.detalleVacio.hidden = false;
    }

    function liberarFotos() {
        s.urls.forEach((url) => URL.revokeObjectURL(url));
        s.urls = [];
    }

    async function seleccionar(id) {
        s.seleccionado = id;
        s.modo = 'inicio';
        const mia = ++s.peticion;
        el.cuerpo.dataset.vista = 'detalle';
        pintarLista();

        const res = await api(`/admin/personas/${id}`);
        if (mia !== s.peticion) return;           // ya eligió a otra persona
        if (!res.ok) {
            if (!res.sesion) avisar(textoError(res), 'error');
            return;
        }
        s.detalle = res.data;
        pintarDetalle();
        cargarFotos(res.data, mia);
    }

    function pintarDetalle() {
        const p = s.detalle;
        liberarFotos();
        el.detalleVacio.hidden = true;
        el.persona.hidden = false;

        el.nombre.textContent = p.nombre;
        el.estado.textContent = ETIQUETA[p.estado] || p.estado;
        el.estado.dataset.estado = p.estado;
        el.hace.textContent = p.estado === 'pendiente'
            ? `Se registró ${haceTiempo(p.creada_en)}`
            : p.revisado_en ? `Revisada ${haceTiempo(p.revisado_en)}` : '';

        pintarAlertas(p);
        pintarFotos(p);
        pintarDatos(p);
        pintarDecision();
        if (!esCelular()) el.nombre.focus({ preventScroll: true });
        else window.scrollTo(0, 0);
    }

    function pintarAlertas(p) {
        el.alertas.textContent = '';
        if (p.estado !== 'pendiente') return;

        if (p.faltan && p.faltan.length) {
            el.alertas.append(h('div', { class: 'alerta alerta-roja' },
                h('strong', { texto: 'Le faltan fotos' }),
                `Falta: ${p.faltan.map((a) => ROTULO[a].toLowerCase()).join(', ')}. No se puede aprobar; puedes rechazar el registro con un mensaje.`));
        }
        for (const parecido of p.parecidos || []) {
            el.alertas.append(h('div', { class: 'alerta' },
                h('strong', { texto: `Se parece a ${parecido.nombre}` }),
                `${parecido.estado === 'aprobado' ? 'Ya tiene acceso' : 'También está pendiente'} (similitud ${parecido.similitud}). `,
                'Revisa que no sea la misma persona registrada dos veces.'));
        }
    }

    function pintarFotos(p) {
        el.fotos.textContent = '';
        el.fotosNota.textContent = '';
        if (p.estado !== 'pendiente') {
            el.fotos.hidden = true;
            el.fotosNota.textContent = 'Las fotos se eliminan al aprobar o rechazar. Del rostro solo se conserva un código numérico para la cámara.';
            return;
        }
        el.fotos.hidden = false;
        for (const angulo of ANGULOS) {
            const subio = p.fotos && p.fotos[angulo];
            const hay = p.fotos_disponibles && p.fotos_disponibles[angulo];
            el.fotos.append(h('figure', { class: 'foto' },
                h('div', { class: 'foto-marco', id: `foto-${angulo}`, texto: !subio ? 'No subió esta foto' : !hay ? 'La foto ya no está disponible' : 'Cargando…' }),
                h('figcaption', { texto: ROTULO[angulo] })));
        }
        el.fotosNota.textContent = 'Toca una foto para verla grande. Se eliminan automáticamente cuando apruebas o rechazas.';
    }

    async function cargarFotos(p, mia) {
        if (p.estado !== 'pendiente') return;
        await Promise.all(ANGULOS.map(async (angulo) => {
            if (!(p.fotos_disponibles && p.fotos_disponibles[angulo])) return;
            const res = await api(`/admin/personas/${p.id}/foto/${angulo}`, { blob: true });
            if (mia !== s.peticion) return;
            const marco = $(`foto-${angulo}`);
            if (!marco) return;
            if (!res.ok) { marco.textContent = 'No se pudo cargar la foto'; return; }
            const url = URL.createObjectURL(res.data);
            s.urls.push(url);
            marco.textContent = '';
            marco.append(h('button', {
                type: 'button', class: 'foto-boton',
                'aria-label': `Ampliar foto: ${ROTULO[angulo]}`,
                onclick: () => ampliar(url, ROTULO[angulo], p.nombre),
            }, h('img', { src: url, alt: `${ROTULO[angulo]} de ${p.nombre}` })));
        }));
    }

    function ampliar(url, rotulo, nombre) {
        el.visorImg.src = url;
        el.visorImg.alt = `${rotulo} de ${nombre}`;
        if (typeof el.visor.showModal === 'function') el.visor.showModal();
    }

    function pintarDatos(p) {
        el.datos.textContent = '';
        const filas = [
            ['Teléfono', formatearTelefono(p.telefono)],
            ['Correo', p.correo],
            ['Se registró', fechaLarga(p.creada_en)],
            ['Número de registro', String(p.id)],
        ];
        if (p.estado !== 'pendiente' && p.revisado_en) filas.push(['Revisada', fechaLarga(p.revisado_en)]);
        if (p.estado === 'rechazado') filas.push(['Mensaje para la persona', p.motivo_rechazo || 'Sin mensaje']);
        for (const [titulo, valor] of filas) {
            el.datos.append(h('dt', { texto: titulo }), h('dd', { texto: valor || 'Sin dato' }));
        }
    }

    // ------------------------------------------------------------------ decisión
    function pintarDecision() {
        const p = s.detalle;
        el.decision.textContent = '';
        el.decision.classList.toggle('abierta', s.modo !== 'inicio');
        if (!p || p.estado === 'rechazado') { el.decision.hidden = true; return; }
        el.decision.hidden = false;

        if (s.modo === 'aprobando') {
            el.decision.append(h('div', { class: 'confirmar' },
                h('p', {}, h('strong', { texto: `¿Aprobar a ${p.nombre}?` }),
                    ' Podrá usar la pluma y sus fotos se eliminarán. Esto no se puede deshacer.'),
                h('div', { class: 'decision-botones' },
                    h('button', { type: 'button', class: 'btn-aprobar', disabled: s.ocupado, onclick: () => decidir('aprobar'), id: 'btn-confirmar' },
                        s.ocupado ? 'Aprobando…' : 'Sí, aprobar'),
                    h('button', { type: 'button', class: 'btn-neutro', disabled: s.ocupado, onclick: () => cambiarModo('inicio') }, 'Cancelar'))));
            return;
        }

        if (s.modo === 'rechazando' || s.modo === 'revocando') {
            const revocando = s.modo === 'revocando';
            const campo = h('textarea', {
                id: 'motivo', maxlength: '500', 'aria-describedby': 'err-motivo',
                placeholder: 'Escribe qué debe corregir la persona.',
            });
            const error = h('p', { class: 'error', id: 'err-motivo', role: 'alert' });
            el.decision.append(h('div', { class: 'confirmar' },
                h('label', { for: 'motivo', texto: revocando ? 'Motivo para quitarle el acceso' : 'Mensaje para la persona (lo verá en su pantalla)' }),
                h('div', { class: 'motivos' },
                    revocando ? null : MOTIVOS_RAPIDOS.map((texto) => h('button', {
                        type: 'button', class: 'motivo-rapido', texto,
                        onclick: () => { campo.value = texto; error.textContent = ''; campo.focus(); },
                    }))),
                campo, error,
                h('div', { class: 'decision-botones' },
                    h('button', {
                        type: 'button', class: 'btn-rechazar', disabled: s.ocupado,
                        onclick: () => {
                            const motivo = campo.value.replace(/\s+/g, ' ').trim();
                            if (motivo.length < 5) { error.textContent = 'Escribe el motivo (mínimo 5 letras).'; campo.focus(); return; }
                            decidir(revocando ? 'revocar' : 'rechazar', motivo);
                        },
                    }, s.ocupado ? 'Guardando…' : revocando ? 'Quitar acceso' : 'Rechazar y eliminar fotos'),
                    h('button', { type: 'button', class: 'btn-neutro', disabled: s.ocupado, onclick: () => cambiarModo('inicio') }, 'Cancelar'))));
            campo.focus();
            return;
        }

        // modo "inicio"
        if (p.estado === 'pendiente') {
            const faltan = p.faltan && p.faltan.length > 0;
            el.decision.append(h('div', { class: 'decision-botones' },
                h('button', { type: 'button', class: 'btn-rechazar', onclick: () => cambiarModo('rechazando') }, 'Rechazar…'),
                h('button', {
                    type: 'button', class: 'btn-aprobar', disabled: faltan,
                    title: faltan ? 'Faltan fotos: no se puede aprobar' : null,
                    onclick: () => cambiarModo('aprobando'),
                }, 'Aprobar…')));
        } else if (p.estado === 'aprobado') {
            el.decision.append(h('div', { class: 'decision-botones' },
                h('button', { type: 'button', class: 'btn-rechazar', onclick: () => cambiarModo('revocando') }, 'Quitar acceso…')));
        }
    }

    function cambiarModo(modo) {
        s.modo = modo;
        pintarDecision();
        if (modo !== 'inicio') el.decision.scrollIntoView({ block: 'nearest' });
        if (modo === 'aprobando') {
            const boton = $('btn-confirmar');
            if (boton) boton.focus();
        }
    }

    /** El que sigue en la lista, para abrirlo después de decidir. */
    function vecino(id) {
        const i = s.lista.findIndex((p) => p.id === id);
        const otro = s.lista[i + 1] || s.lista[i - 1];
        return otro ? otro.id : null;
    }

    async function decidir(tipo, motivo) {
        if (s.ocupado) return;
        const p = s.detalle;
        const siguiente = vecino(p.id);
        s.ocupado = true;
        pintarDecision();

        const res = await api(`/admin/personas/${p.id}/${tipo}`, {
            metodo: 'POST', cuerpo: motivo ? { motivo } : null,
        });
        s.ocupado = false;

        if (res.sesion) return;
        if (!res.ok) {
            pintarDecision();
            avisar(textoError(res), 'error');
            if (res.status === 409) { await refrescar(); }
            return;
        }

        const verbo = { aprobar: 'aprobada', rechazar: 'rechazada', revocar: 'sin acceso' }[tipo];
        avisar(`${p.nombre}: ${verbo}.` + (tipo === 'revocar' ? '' : ' Sus fotos se eliminaron.'));
        if (res.data && res.data.fotos_eliminadas === false) {
            avisar('No se pudieron borrar las fotos del servidor. Avisa al responsable del sistema para que las elimine.', 'error', true);
        }

        s.modo = 'inicio';
        s.seleccionado = null;
        s.detalle = null;
        await Promise.all([cargarCuentas(), cargarLista()]);
        const abrir = siguiente && s.lista.some((x) => x.id === siguiente) ? siguiente : null;
        if (abrir) {
            seleccionar(abrir);
        } else {
            ocultarDetalle();
            pintarLista();
            el.cuerpo.dataset.vista = 'lista';
        }
    }

    // --------------------------------------------------------------------- tema
    function aplicarTema(tema) {
        document.documentElement.dataset.theme = tema;
        el.btnTema.textContent = tema === 'claro' ? 'Tema oscuro' : 'Tema claro';
    }

    // ------------------------------------------------------------------ eventos
    function conectarEventos() {
        el.formLogin.addEventListener('submit', iniciarSesion);
        el.btnSalir.addEventListener('click', () => cerrarSesion(''));
        el.btnVolver.addEventListener('click', () => { el.cuerpo.dataset.vista = 'lista'; });
        el.pestanas.forEach((pestana) => pestana.addEventListener('click', () => cambiarPestana(pestana.dataset.estado)));

        el.btnTema.addEventListener('click', () => {
            const nuevo = document.documentElement.dataset.theme === 'claro' ? 'oscuro' : 'claro';
            aplicarTema(nuevo);
            escribir(CLAVE_TEMA, nuevo, localStorage);
        });

        el.visorCerrar.addEventListener('click', () => el.visor.close());
        el.visor.addEventListener('click', (e) => { if (e.target === el.visor) el.visor.close(); });
        el.visor.addEventListener('close', () => { el.visorImg.removeAttribute('src'); });
    }

    // ------------------------------------------------------------------- inicio
    async function iniciar() {
        aplicarTema(document.documentElement.dataset.theme === 'claro' ? 'claro' : 'oscuro');
        conectarEventos();

        const guardada = leer(CLAVE_SESION);
        if (guardada) {
            s.clave = guardada;
            const res = await api('/admin/resumen');
            if (res.ok) { entrar(res.data); return; }
            s.clave = '';
            borrar(CLAVE_SESION);
        }
        el.login.hidden = false;
        el.clave.focus();
    }

    iniciar();
})();
