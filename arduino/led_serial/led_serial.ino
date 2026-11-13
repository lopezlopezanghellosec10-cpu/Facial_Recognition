const int LED_PIN = 8;

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // Abre la comunicación USB/Serial a 9600 bits por segundo.
  Serial.begin(9600);
}

void loop() {
  // Solo leemos cuando ya llegó un carácter por el puerto serial.
  if (Serial.available() > 0) {
    char command = Serial.read();

    if (command == '1') {
      digitalWrite(LED_PIN, HIGH);
    } else if (command == '0') {
      digitalWrite(LED_PIN, LOW);
    }
    // Otros caracteres, como el Enter del Monitor Serie, se ignoran.
  }
}
