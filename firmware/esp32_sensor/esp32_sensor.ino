/*
  ExamSentry 센서 펌웨어 (ESP32 DevKit, Arduino-ESP32 코어 2.x / 3.x)
  ※ 컴파일 확인: 2026-11-19, esp32 보드 패키지 3.3.13 (실기 테스트는 보드 도착 후)
  ※ 중요: Wi-Fi + 블루투스를 같이 써서 기본 설정에는 안 들어감(125%).
     Arduino IDE → 툴 → Partition Scheme → "Huge APP (3MB No OTA/1MB SPIFFS)" 로 바꾸고 업로드 (52%).

  하는 일: 1초 BLE 스캔 ↔ 1초 Wi-Fi 패킷 엿듣기(고정 채널)를 번갈아 반복.
          1초 동안 같은 기기에서 온 패킷을 묶어 한 줄로 출력 (시리얼이 넘치지 않게).
  출력:   A,BLE,aa:bb:cc:dd:ee:ff,-58,A,3      센서,종류,주소,평균세기,프레임,패킷수
          A,WIFI,3c:71:bf:12:a0:4e,-61,D,42    프레임 D=데이터가 절반 이상, M=관리
  패킷 내용(payload)은 읽지 않는다. 주소와 세기만 본다.

  보드마다 SENSOR_ID 를 A(앞왼쪽) B(앞오른쪽) C(뒤왼쪽) D(뒤오른쪽) 로 바꿔서 업로드.
  보드레이트 921600 (serial_reader.py 기본값과 같음).
*/
#include <Arduino.h>
#include <WiFi.h>
#include "esp_wifi.h"
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

#define SENSOR_ID "A"     // ← 보드마다 변경
#define WIFI_CH   6       // ← 시연 핫스팟 채널과 같게 (핫스팟 설정에서 채널 고정)
#define SLOT_MS   1000
#define MAXE      48      // 1초 동안 기억할 최대 기기 수

struct Entry { uint8_t mac[6]; int32_t rssiSum; uint16_t n; uint16_t data; bool used; };
static Entry table[MAXE];
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static BLEScan* scan;

static void addPacket(const uint8_t* mac, int rssi, bool isData) {
  portENTER_CRITICAL(&mux);
  int freeIdx = -1;
  for (int i = 0; i < MAXE; i++) {
    if (table[i].used) {
      if (memcmp(table[i].mac, mac, 6) == 0) {
        table[i].rssiSum += rssi; table[i].n++; if (isData) table[i].data++;
        portEXIT_CRITICAL(&mux);
        return;
      }
    } else if (freeIdx < 0) freeIdx = i;
  }
  if (freeIdx >= 0) {
    Entry& e = table[freeIdx];
    memcpy(e.mac, mac, 6); e.rssiSum = rssi; e.n = 1; e.data = isData ? 1 : 0; e.used = true;
  }
  portEXIT_CRITICAL(&mux);
}

static void flush(const char* kind) {
  static Entry copy[MAXE];
  portENTER_CRITICAL(&mux);
  memcpy(copy, table, sizeof(table));
  memset(table, 0, sizeof(table));
  portEXIT_CRITICAL(&mux);
  bool ble = kind[0] == 'B';
  for (int i = 0; i < MAXE; i++) {
    if (!copy[i].used) continue;
    const uint8_t* m = copy[i].mac;
    char fr = ble ? 'A' : (copy[i].data * 2 >= copy[i].n ? 'D' : 'M');
    Serial.printf("%s,%s,%02x:%02x:%02x:%02x:%02x:%02x,%d,%c,%u\n", SENSOR_ID, kind,
                  m[0], m[1], m[2], m[3], m[4], m[5], (int)(copy[i].rssiSum / copy[i].n), fr, copy[i].n);
  }
}

// ---- BLE ----
class AdvCB : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) override {
    uint8_t mac[6];
    unsigned int b[6];
    // 코어 버전마다 getNative() 형이 달라서 문자열에서 읽는다
    if (sscanf(d.getAddress().toString().c_str(), "%x:%x:%x:%x:%x:%x",
               &b[0], &b[1], &b[2], &b[3], &b[4], &b[5]) == 6) {
      for (int i = 0; i < 6; i++) mac[i] = (uint8_t)b[i];
      addPacket(mac, d.getRSSI(), false);
    }
  }
};

// ---- Wi-Fi (promiscuous) ----
static void sniffer(void* buf, wifi_promiscuous_pkt_type_t type) {
  if (type != WIFI_PKT_MGMT && type != WIFI_PKT_DATA) return;
  const wifi_promiscuous_pkt_t* p = (const wifi_promiscuous_pkt_t*)buf;
  if (p->rx_ctrl.sig_len < 24) return;
  const uint8_t* hdr = p->payload;         // 802.11 헤더만 본다
  const uint8_t* addr2 = hdr + 10;         // 보낸 기기 주소
  addPacket(addr2, p->rx_ctrl.rssi, type == WIFI_PKT_DATA);
}

void setup() {
  Serial.begin(921600);
  delay(300);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  wifi_promiscuous_filter_t filt = { .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA };
  esp_wifi_set_promiscuous_filter(&filt);
  esp_wifi_set_promiscuous_rx_cb(&sniffer);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(WIFI_CH, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous(false);

  BLEDevice::init("");
  scan = BLEDevice::getScan();
  scan->setAdvertisedDeviceCallbacks(new AdvCB(), true);   // true = 같은 기기 반복 광고도 받기
  scan->setActiveScan(false);                              // 수동 스캔 (요청 패킷 안 보냄)
  scan->setInterval(100);
  scan->setWindow(99);
  Serial.printf("# ExamSentry sensor %s ready, wifi ch %d\n", SENSOR_ID, WIFI_CH);
}

void loop() {
  scan->start(SLOT_MS / 1000, false);   // 1초 BLE (블로킹)
  scan->clearResults();
  flush("BLE");

  esp_wifi_set_promiscuous(true);       // 1초 Wi-Fi
  esp_wifi_set_channel(WIFI_CH, WIFI_SECOND_CHAN_NONE);
  delay(SLOT_MS);
  esp_wifi_set_promiscuous(false);
  flush("WIFI");
}
