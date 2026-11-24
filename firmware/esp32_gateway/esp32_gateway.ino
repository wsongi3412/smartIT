/*
  ExamSentry 수신기 펌웨어 (ESP32 DevKit 1대, 노트북 USB에 꽂음) — 11-24
  ※ 컴파일 확인: esp32 보드 패키지 3.3.13 (실기 테스트 전). 기본 Partition Scheme 그대로 됨.

  하는 일: 센서 A~D가 ESP-NOW로 보낸 기록을 받아서, 센서를 USB로 꽂았을 때와 **똑같은 줄**로 출력.
          A,BLE,aa:bb:cc:dd:ee:ff,-58,A,3
          → serial_reader.py 를 그대로 쓴다 (포트가 4개 → 1개가 될 뿐).
  '#' 로 시작하는 줄은 상태 표시 (serial_reader.py 가 무시):
          # gateway MAC ...           ← 센서 펌웨어 GATEWAY_MAC 에 넣으면 재전송까지 됨
          # 10s A:20 B:19 C:20 D:0 lost A:0 B:1 C:0 D:0   ← 센서별 10초간 받은 패킷 수 / 빠진 패킷 수
  센서와 같은 채널(WIFI_CH)이어야 받는다.
*/
#include <Arduino.h>
#include <WiFi.h>
#include "esp_wifi.h"
#include <esp_now.h>

#define WIFI_CH 6     // ← 센서 펌웨어와 같게
#define BAUD 460800   // serial_reader.py --baud 와 같게 (CH340 보드는 921600에서 깨짐)
#define HOTSPOT_SSID "iPhone"   // ← 시연 핫스팟 이름. 켜질 때 이 핫스팟 채널을 찾아 맞춤 (아이폰: "호환성 최대화" 켜야 2.4GHz)

struct __attribute__((packed)) Rec { uint8_t mac[6]; int8_t rssi; char frame; uint16_t n; };
struct __attribute__((packed)) Pkt { uint8_t magic[2]; char sensor; char kind; uint8_t seq; uint8_t cnt; Rec r[24]; };

// 받은 패킷은 콜백(무선 작업)에서 큐에 넣기만 하고, 출력은 loop()에서
static QueueHandle_t q;
static int got[4], lost[4];
static int lastSeq[4] = {-1, -1, -1, -1};

#if ESP_ARDUINO_VERSION_MAJOR >= 3
static void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
#else
static void onRecv(const uint8_t* mac, const uint8_t* data, int len) {
#endif
  if (len < 6 || len > (int)sizeof(Pkt) || data[0] != 'E' || data[1] != 'S') return;
  Pkt p = {};
  memcpy(&p, data, len);
  xQueueSend(q, &p, 0);   // 가득 차면 버림 (loop가 따라잡지 못한 경우)
}

// 켜질 때 핫스팟(HOTSPOT_SSID)을 찾아 그 채널로 맞춘다 (아이폰은 채널을 못 고름). 못 찾으면 WIFI_CH.
static uint8_t wifiCh = WIFI_CH;
static void findHotspotChannel() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  for (int tryN = 0; tryN < 3; tryN++) {
    int n = WiFi.scanNetworks();
    for (int i = 0; i < n; i++) {
      if (WiFi.SSID(i) == HOTSPOT_SSID && WiFi.channel(i) <= 13) {
        wifiCh = WiFi.channel(i);
        Serial.printf("# hotspot '%s' found on ch %d\n", HOTSPOT_SSID, wifiCh);
        WiFi.scanDelete();
        return;
      }
    }
    WiFi.scanDelete();
  }
  Serial.printf("# hotspot '%s' NOT found (2.4GHz?) -> ch %d\n", HOTSPOT_SSID, wifiCh);
}

void setup() {
  Serial.begin(BAUD);
  delay(300);
  q = xQueueCreate(64, sizeof(Pkt));
  findHotspotChannel();
  esp_wifi_set_promiscuous(true);                       // 채널 고정용
  esp_wifi_set_channel(wifiCh, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous(false);
  if (esp_now_init() != ESP_OK) {
    Serial.println("# ESP-NOW 시작 실패");
  }
  esp_now_register_recv_cb(onRecv);
  Serial.printf("# gateway MAC %s, wifi ch %d\n", WiFi.macAddress().c_str(), wifiCh);
}

void loop() {
  Pkt p;
  while (xQueueReceive(q, &p, pdMS_TO_TICKS(50)) == pdTRUE) {
    int si = p.sensor - 'A';
    if (si < 0 || si > 3) continue;
    got[si]++;
    if (lastSeq[si] >= 0) lost[si] += (uint8_t)(p.seq - lastSeq[si] - 1);
    lastSeq[si] = p.seq;
    const char* kind = p.kind == 'B' ? "BLE" : "WIFI";
    for (int i = 0; i < p.cnt && i < 24; i++) {
      const Rec& r = p.r[i];
      Serial.printf("%c,%s,%02x:%02x:%02x:%02x:%02x:%02x,%d,%c,%u\n", p.sensor, kind,
                    r.mac[0], r.mac[1], r.mac[2], r.mac[3], r.mac[4], r.mac[5], r.rssi, r.frame, r.n);
    }
  }
  static uint32_t t0 = millis();
  if (millis() - t0 >= 10000) {
    t0 = millis();
    Serial.printf("# 10s A:%d B:%d C:%d D:%d lost A:%d B:%d C:%d D:%d\n",
                  got[0], got[1], got[2], got[3], lost[0], lost[1], lost[2], lost[3]);
    memset(got, 0, sizeof(got)); memset(lost, 0, sizeof(lost));
  }
}
