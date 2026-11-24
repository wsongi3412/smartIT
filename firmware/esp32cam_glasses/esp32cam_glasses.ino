/*
  ExamSentry — "AI 안경" 대역 펌웨어 (ESP32-CAM, AI-Thinker 보드)
  ※ 컴파일 확인: 2026-11-19, esp32 보드 패키지 3.3.13, 보드 "AI Thinker ESP32-CAM" (실기 테스트는 도착 후)

  진짜 AI 안경이 내는 신호를 흉내 낸다:
    1) 블루투스(BLE) 광고를 계속 보냄        → 휴대폰과 연결을 유지하는 안경
    2) 30초마다 사진을 찍어 Wi-Fi로 몰아 보냄  → 찍은 사진을 휴대폰/서버로 올리는 안경
    3) 10분마다 MAC 주소를 새로 바꿈 (재부팅)   → 주소를 주기적으로 바꾸는 실제 기기
       (AI가 "주소가 바뀌어도 같은 자리의 같은 기기"로 이어 붙이는지 실기로 시험)

  ★ 측정 모드 (MEASURE_MODE 1, 11-25): 신호 지도 측정 때 '비콘' 대신 쓴다 → ESP32 비콘을 따로 안 사도 됨.
     - 주소(MAC)를 바꾸지 않음 → stage_log.py --id 로 계속 따라갈 수 있음
     - BLE 광고 계속 + Wi-Fi는 30초마다가 아니라 0.1초마다 작은 패킷 → 자리마다 BLE·Wi-Fi 둘 다 고르게 잡힘
     - 3초마다 시리얼에 "MEASURE BLE xx:.. WIFI xx:.." 출력 → BLE 바퀴는 BLE 주소, Wi-Fi 바퀴는 WIFI 주소를 --id 에
     시험 연출·시연 때는 다시 0으로 올린다.

  업로드: Arduino IDE → 보드 "AI Thinker ESP32-CAM", ESP32-CAM-MB 보드에 꽂아 USB 연결.
  설정: 아래 WIFI_SSID / WIFI_PASS 를 시연용 핫스팟으로 바꾸기 (센서 펌웨어 WIFI_CH 와 같은 채널).
  시리얼(115200)에 현재 MAC과 버스트 기록이 찍힌다. → 연출 정답 CSV 에 이 MAC 을 적는다.
*/
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <BLEDevice.h>
#include <BLEAdvertising.h>
#include "esp_camera.h"
#include "esp_system.h"
#if __has_include("esp_mac.h")
#include "esp_mac.h"
#endif

// ---------- 설정 ----------
#define MEASURE_MODE   0      // ← 1 = 신호 지도 측정용 (비콘 대신), 0 = AI 안경 흉내 (시연)
const char* WIFI_SSID = "ExamSentry-Hotspot";   // ← 시연 핫스팟 이름
const char* WIFI_PASS = "change-me";            // ← 비밀번호
#define BURST_EVERY_S  30     // 몇 초마다 사진을 보낼지
#define BURST_MS       3000   // 한 번에 몇 ms 동안 몰아 보낼지
#if MEASURE_MODE
#define ROTATE_MIN     0      // 측정 모드: 주소 고정
#else
#define ROTATE_MIN     10     // 몇 분마다 MAC을 바꿀지 (0 = 안 바꿈)
#endif
#define UDP_PORT       5005   // 받는 쪽이 없어도 됨. 공중에 Wi-Fi 데이터 프레임이 나가는 게 목적

// ---------- AI-Thinker ESP32-CAM 핀 ----------
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

WiFiUDP udp;
bool cameraOk = false;
uint32_t lastBurst = 0;
uint8_t dummy[1024];

// 부팅할 때마다 무작위 MAC (로컬 관리 주소) → 재부팅 = 주소 교체
static void randomizeMac() {
  uint8_t mac[6];
  for (int i = 0; i < 6; i++) mac[i] = esp_random() & 0xFF;
  mac[0] = (mac[0] & 0xFC) | 0x02;   // 유니캐스트 + 로컬 관리 비트
  esp_base_mac_addr_set(mac);        // Wi-Fi·BLE 켜기 전에 호출해야 함
}

static bool initCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM; c.pin_d1 = Y3_GPIO_NUM; c.pin_d2 = Y4_GPIO_NUM; c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM; c.pin_d5 = Y7_GPIO_NUM; c.pin_d6 = Y8_GPIO_NUM; c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM; c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM; c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM; c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM; c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_QVGA;     // 320x240, 작게
  c.jpeg_quality = 12;
  c.fb_count = 1;
  return esp_camera_init(&c) == ESP_OK;
}

// 사진 1장(없으면 더미)을 BURST_MS 동안 반복해서 UDP로 보냄 → Wi-Fi 데이터 프레임이 몰려 나감
static void burst() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("# burst skipped: wifi not connected");
    return;
  }
  camera_fb_t* fb = cameraOk ? esp_camera_fb_get() : nullptr;
  const uint8_t* buf = fb ? fb->buf : dummy;
  size_t len = fb ? fb->len : sizeof(dummy);
  IPAddress bcast = WiFi.broadcastIP();
  uint32_t t0 = millis(), sent = 0;
  while (millis() - t0 < BURST_MS) {
    for (size_t off = 0; off < len && millis() - t0 < BURST_MS; off += 1024) {
      size_t n = min((size_t)1024, len - off);
      udp.beginPacket(bcast, UDP_PORT);
      udp.write(buf + off, n);
      udp.endPacket();
      sent++;
      delay(2);
    }
  }
  if (fb) esp_camera_fb_return(fb);
  Serial.printf("# burst: %u packets, photo %s (%u bytes)\n", sent, fb ? "yes" : "dummy", (unsigned)len);
}

void setup() {
  Serial.begin(115200);
  if (ROTATE_MIN > 0) randomizeMac();
  for (size_t i = 0; i < sizeof(dummy); i++) dummy[i] = i & 0xFF;

  cameraOk = initCamera();

  BLEDevice::init("ES-GLASS");
  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->setMinInterval(0x00A0);   // 100ms
  adv->setMaxInterval(0x00A0);
  adv->start();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 10000) delay(200);

  Serial.printf("# ES-GLASS ready | BLE %s | WiFi %s | camera %s | wifi %s\n",
                BLEDevice::getAddress().toString().c_str(), WiFi.macAddress().c_str(),
                cameraOk ? "ok" : "FAIL(dummy)", WiFi.status() == WL_CONNECTED ? "connected" : "NOT connected");
  lastBurst = millis();
}

void loop() {
#if MEASURE_MODE
  static uint32_t lastPkt = 0, lastPrint = 0;
  if (WiFi.status() == WL_CONNECTED && millis() - lastPkt >= 100) {   // 0.1초마다 작은 Wi-Fi 데이터 프레임
    udp.beginPacket(WiFi.broadcastIP(), UDP_PORT);
    udp.write(dummy, 200);
    udp.endPacket();
    lastPkt = millis();
  }
  if (millis() - lastPrint >= 3000) {
    Serial.printf("MEASURE BLE %s WIFI %s %s\n", BLEDevice::getAddress().toString().c_str(),
                  WiFi.macAddress().c_str(), WiFi.status() == WL_CONNECTED ? "" : "(wifi NOT connected)");
    lastPrint = millis();
  }
  if (WiFi.status() != WL_CONNECTED) {
    static uint32_t lastTry = 0;
    if (millis() - lastTry > 5000) { WiFi.reconnect(); lastTry = millis(); }
  }
  delay(10);
  return;
#endif
  if (millis() - lastBurst >= BURST_EVERY_S * 1000UL) {
    burst();
    lastBurst = millis();
  }
  if (ROTATE_MIN > 0 && millis() > ROTATE_MIN * 60000UL) {
    Serial.println("# rotating MAC (restart)");
    delay(100);
    ESP.restart();               // 재부팅하면 setup()에서 새 MAC
  }
  if (WiFi.status() != WL_CONNECTED) {   // 핫스팟이 끊기면 다시 연결
    static uint32_t lastTry = 0;
    if (millis() - lastTry > 5000) { WiFi.reconnect(); lastTry = millis(); }
  }
  delay(50);
}
