
#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>

#include "bme68xLibrary.h"
#include "secrets.h"

// ==========================================
// CONFIGURACOES
// ==========================================

const int PINO_SDA = 21;
const int PINO_SCL = 22;

const char* DEVICE_ID = "esp32-001";

const char* SERVER_URL =
    "http://10.149.193.105:8000/api/v1/readings";

const unsigned long INTERVALO_ENVIO = 5000;

Bme68x bme;

uint8_t enderecoSensor = 0;

unsigned long ultimoEnvio = 0;
unsigned long ultimaTentativaWiFi = 0;

// ==========================================
// IDENTIFICACAO DO SENSOR
// ==========================================

bool identificarSensor() {

    const uint8_t enderecos[] = {0x76, 0x77};

    for (int i = 0; i < 2; i++) {

        Wire.beginTransmission(enderecos[i]);

        if (Wire.endTransmission() == 0) {

            enderecoSensor = enderecos[i];

            return true;
        }
    }

    return false;
}

// ==========================================
// CONEXAO WIFI
// ==========================================


void conectarWiFi() {

    WiFi.mode(WIFI_STA);

    WiFi.setSleep(false);

    Serial.println("\n========== WIFI ==========");

    Serial.print("Rede configurada: ");

    Serial.println(WIFI_SSID);

    Serial.println("Iniciando conexao...");

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long inicio = millis();

    while (
        WiFi.status() != WL_CONNECTED &&
        millis() - inicio < 30000
    ) {

        Serial.print(".");

        Serial.print(" Status: ");

        Serial.println(WiFi.status());

        delay(1000);
    }

    if (WiFi.status() == WL_CONNECTED) {

        Serial.println("\nWIFI CONECTADO!");

        Serial.print("IP do ESP32: ");

        Serial.println(WiFi.localIP());

        Serial.print("Intensidade do sinal: ");

        Serial.print(WiFi.RSSI());

        Serial.println(" dBm");

    }

    else {

        Serial.println("\nFALHA NA CONEXAO WIFI!");

        Serial.print("Status final: ");

        Serial.println(WiFi.status());

        Serial.println("Verifique rede e senha.");
    }

    Serial.println("==========================");
}

// ==========================================
// MANUTENCAO DA CONEXAO
// ==========================================

void verificarWiFi() {

    if (WiFi.status() == WL_CONNECTED) {

        return;
    }

    if (millis() - ultimaTentativaWiFi >= 10000) {

        ultimaTentativaWiFi = millis();

        Serial.println("Tentando reconectar ao Wi-Fi...");

        WiFi.disconnect();

        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
}

// ==========================================
// ENVIO DOS DADOS PARA A API
// ==========================================

void enviarLeitura(bme68xData dados) {

    if (WiFi.status() != WL_CONNECTED) {

        Serial.println("Leitura nao enviada: Wi-Fi desconectado.");

        return;
    }

    WiFiClient client;

    HTTPClient http;

    if (!http.begin(client, SERVER_URL)) {

        Serial.println("Erro ao iniciar requisicao HTTP.");

        return;
    }

    http.setTimeout(5000);

    http.addHeader(
        "Content-Type",
        "application/json"
    );

    // Montagem do JSON

    String json = "{";

    json += "\"device_id\":\"";
    json += DEVICE_ID;
    json += "\",";

    json += "\"sensor\":\"BME688\",";

    json += "\"temperature_c\":";
    json += String(dados.temperature, 2);
    json += ",";

    json += "\"humidity_pct\":";
    json += String(dados.humidity, 2);
    json += ",";

    json += "\"pressure_hpa\":";
    json += String(dados.pressure / 100.0f, 2);
    json += ",";

    json += "\"gas_resistance_ohm\":";
    json += String(dados.gas_resistance, 2);

    json += "}";

    Serial.println("\nEnviando dados para o servidor...");

    Serial.println(json);

    // Envio HTTP POST

    int codigoHTTP = http.POST(json);

    if (codigoHTTP > 0) {

        Serial.print("Codigo HTTP: ");

        Serial.println(codigoHTTP);

        String resposta = http.getString();

        Serial.println("Resposta do servidor:");

        Serial.println(resposta);

        if (codigoHTTP == 201) {

            Serial.println("Leitura armazenada com sucesso!");
        }

        else {

            Serial.println("Servidor respondeu, mas houve uma falha.");
        }
    }

    else {

        Serial.print("Falha HTTP: ");

        Serial.println(
            http.errorToString(codigoHTTP)
        );
    }

    http.end();
}

// ==========================================
// INICIALIZACAO
// ==========================================

void setup() {

    Serial.begin(115200);

    delay(1500);

    Serial.println("\n================================");

    Serial.println("MEDIDOR DE GLICOSE ACESSIVEL");

    Serial.println("ESP32 + BME688 + FASTAPI");

    Serial.println("================================");

    // Inicializa I2C

    Wire.begin(PINO_SDA, PINO_SCL);

    Wire.setClock(100000);

    // Identifica o sensor

    if (!identificarSensor()) {

        Serial.println("ERRO: BME688 nao encontrado!");

        while (true) {

            delay(1000);
        }
    }

    Serial.print("BME688 encontrado: 0x");

    Serial.println(enderecoSensor, HEX);

    // Inicializa o sensor

    bme.begin(enderecoSensor, Wire);

    if (bme.checkStatus() == BME68X_ERROR) {

        Serial.println("Erro ao inicializar BME688!");

        Serial.println(bme.statusString());

        while (true) {

            delay(1000);
        }
    }

    bme.setTPH();

    bme.setHeaterProf(300, 100);

    Serial.println("BME688 inicializado!");

    // Conecta ao Wi-Fi

    conectarWiFi();

    Serial.println("\nSistema pronto!");

}

// ==========================================
// LOOP PRINCIPAL
// ==========================================

void loop() {

    verificarWiFi();

    bme68xData dados;

    // Solicita medicao

    bme.setOpMode(BME68X_FORCED_MODE);

    delayMicroseconds(bme.getMeasDur());

    if (bme.fetchData()) {

        bme.getData(dados);

        Serial.println("\n========== BME688 ==========");

        Serial.print("Temperatura: ");

        Serial.print(dados.temperature);

        Serial.println(" C");

        Serial.print("Umidade: ");

        Serial.print(dados.humidity);

        Serial.println(" %");

        Serial.print("Pressao: ");

        Serial.print(dados.pressure / 100.0f);

        Serial.println(" hPa");

        Serial.print("Resistencia do gas: ");

        Serial.print(dados.gas_resistance);

        Serial.println(" ohms");

        // Envia uma medicao a cada 5 segundos

        if (millis() - ultimoEnvio >= INTERVALO_ENVIO) {

            ultimoEnvio = millis();

            enviarLeitura(dados);
        }
    }

    else {

        Serial.println("Nenhuma leitura disponivel.");
    }

    delay(500);
}
