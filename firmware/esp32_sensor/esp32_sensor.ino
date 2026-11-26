/*
  ExamSentry 센서 펌웨어 (ESP32 DevKit, Arduino-ESP32 코어 2.x / 3.x)
  ※ 컴파일 확인: 2026-11-19, esp32 보드 패키지 3.3.13 (실기 테스트는 보드 도착 후)
  ※ 중요: Wi-Fi + 블루투스를 같이 써서 기본 설정에는 안 들어감(125%).
     Arduino IDE → 툴 → Partition Scheme → "Huge APP (3MB No OTA/1MB SPIFFS)" 로 바꾸고 업로드 (52%).

  하는 일: 1초 BLE 스캔 ↔ 1초 Wi-Fi 패킷 엿듣기(고정 채널)를 번갈아 반복.
          1초 동안 같은 기기에서 온 패킷을 묶어 한 줄로 출력 (시리얼이 넘치지 않게).
  보내는 길 (11-24): ESP-NOW 무선 → 노트북에 꽂힌 수신기(esp32_gateway)가 같은 줄로 출력.
          → 센서는 보조배터리·USB 충전기로만 켜면 됨 (노트북 연결 불필요).
          USB로 노트북에 꽂으면 예전처럼 시리얼에도 같은 줄이 찍힌다 (둘 다 동시에 됨).
          다른 센서가 보내는 ESP-NOW 패킷은 엿듣기에서 뺀다 (센서끼리 서로를 기기로 세지 않게).
  출력:   A,BLE,aa:bb:cc:dd:ee:ff,-58,A,3      센서,종류,주소,평균세기,프레임,패킷수
          A,WIFI,3c:71:bf:12:a0:4e,-61,D,42    프레임 D=데이터가 절반 이상, M=관리
  상태 LED (보드 파란 LED, 11-26):
          켜질 때 몇 초 계속 켜짐 = 핫스팟 찾는 중
          1초마다 짧게 1번 깜빡     = 정상 (듣고 보내는 중)
          1초마다 빠르게 3번 깜빡   = 핫스팟을 못 찾음 → 기본 채널(WIFI_CH)로 동작 중. 핫스팟·"호환성 최대화" 확인 후 다시 켜기
          꺼져 있음               = 전원 없음
  패킷 내용(payload)은 읽지 않는다. 주소와 세기만 본다.

  보드마다 SENSOR_ID 를 A(앞왼쪽) B(앞오른쪽) C(뒤왼쪽) D(뒤오른쪽) 로 바꿔서 업로드.
  보드레이트 BAUD=460800 (serial_reader.py 기본값과 같음). CH340 보드는 921600에서 글자가 깨짐.
  업로드가 "No more data to read" 로 실패하면 툴 → Upload Speed → 460800 (또는 115200).
*/
#include <Arduino.h>
#include <WiFi.h>
#include "esp_wifi.h"
#include <esp_now.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

#define SENSOR_ID "A"     // ← 보드마다 변경
#define WIFI_CH   6       // ← 시연 핫스팟 채널과 같게 (핫스팟 설정에서 채널 고정)
#define BAUD      460800  // CH340 보드는 921600에서 글자가 깨짐 (11-25 실기 확인). serial_reader.py --baud 와 같게
#define HOTSPOT_SSID "iPhone"   // ← 시연 핫스팟 이름. 켜질 때 이 핫스팟 채널을 찾아 맞춤 (아이폰: "호환성 최대화" 켜야 2.4GHz)
#define SLOT_MS   1000
#define MAXE      48      // 1초 동안 기억할 최대 기기 수
// 수신기(esp32_gateway) 주소. 수신기 시리얼 첫 줄 "# gateway MAC ..." 을 보고 바꾸면 재전송까지 되어 더 안정적.
// 그대로(FF:...) 두면 방송으로 보냄 (설정 없이 됨, 대신 재전송 없음).
#define LED_PIN   2       // 보드 파란 LED (대부분의 ESP32 DevKit). 없는 보드면 아무 일도 안 일어남
static volatile uint8_t ledBlinks = 0;   // 깜빡일 횟수 (loop가 요청, ledTask가 처리 → 듣는 시간을 안 뺏음)
static bool hotspotFound = false;
static void ledTask(void*) {
  for (;;) {
    uint8_t n = ledBlinks;
    if (n) {
      ledBlinks = 0;
      for (uint8_t i = 0; i < n; i++) {
        digitalWrite(LED_PIN, HIGH); vTaskDelay(pdMS_TO_TICKS(40));
        digitalWrite(LED_PIN, LOW);  vTaskDelay(pdMS_TO_TICKS(80));
      }
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

static uint8_t GATEWAY_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// ESP-NOW 패킷: 머리 6바이트 + 기기 기록 10바이트 × 최대 24개 = 246바이트 (한도 250)
struct __attribute__((packed)) Rec { uint8_t mac[6]; int8_t rssi; char frame; uint16_t n; };
struct __attribute__((packed)) Pkt { uint8_t magic[2]; char sensor; char kind; uint8_t seq; uint8_t cnt; Rec r[24]; };
static Pkt pkt;
static uint8_t seq = 0;

static void sendPkt() {
  if (!pkt.cnt) return;
  pkt.magic[0] = 'E'; pkt.magic[1] = 'S'; pkt.sensor = SENSOR_ID[0]; pkt.seq = seq++;
  esp_now_send(GATEWAY_MAC, (uint8_t*)&pkt, 6 + pkt.cnt * sizeof(Rec));
  pkt.cnt = 0;
}

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
  pkt.kind = kind[0]; pkt.cnt = 0;
  for (int i = 0; i < MAXE; i++) {
    if (!copy[i].used) continue;
    const uint8_t* m = copy[i].mac;
    char fr = ble ? 'A' : (copy[i].data * 2 >= copy[i].n ? 'D' : 'M');
    Serial.printf("%s,%s,%02x:%02x:%02x:%02x:%02x:%02x,%d,%c,%u\n", SENSOR_ID, kind,
                  m[0], m[1], m[2], m[3], m[4], m[5], (int)(copy[i].rssiSum / copy[i].n), fr, copy[i].n);
    Rec& r = pkt.r[pkt.cnt++];
    memcpy(r.mac, m, 6); r.rssi = (int8_t)(copy[i].rssiSum / copy[i].n); r.frame = fr; r.n = copy[i].n;
    if (pkt.cnt == 24) { sendPkt(); delay(2); }
  }
  sendPkt();
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
  // ESP-NOW(다른 센서가 보내는 것) 빼기: 액션 프레임 + 제조사 전용(127) + Espressif OUI 18:fe:34
  if (hdr[0] == 0xD0 && p->rx_ctrl.sig_len >= 28 && hdr[24] == 127 &&
      hdr[25] == 0x18 && hdr[26] == 0xfe && hdr[27] == 0x34) return;
  const uint8_t* addr2 = hdr + 10;         // 보낸 기기 주소
  addPacket(addr2, p->rx_ctrl.rssi, type == WIFI_PKT_DATA);
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
        hotspotFound = true;
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
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);          // 핫스팟 찾는 동안 계속 켜짐
  findHotspotChannel();
  digitalWrite(LED_PIN, LOW);
  xTaskCreate(ledTask, "led", 1536, nullptr, 1, nullptr);
  wifi_promiscuous_filter_t filt = { .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA };
  esp_wifi_set_promiscuous_filter(&filt);
  esp_wifi_set_promiscuous_rx_cb(&sniffer);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(wifiCh, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous(false);

  if (esp_now_init() == ESP_OK) {
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, GATEWAY_MAC, 6);
    peer.channel = wifiCh;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    esp_now_add_peer(&peer);
  } else {
    Serial.println("# ESP-NOW 시작 실패 (USB 시리얼로만 출력)");
  }

  BLEDevice::init("");
  scan = BLEDevice::getScan();
  scan->setAdvertisedDeviceCallbacks(new AdvCB(), true);   // true = 같은 기기 반복 광고도 받기
  scan->setActiveScan(false);                              // 수동 스캔 (요청 패킷 안 보냄)
  scan->setInterval(100);
  scan->setWindow(99);
  Serial.printf("# ExamSentry sensor %s ready, wifi ch %d, ESP-NOW -> %02x:%02x:%02x:%02x:%02x:%02x\n", SENSOR_ID, wifiCh,
                GATEWAY_MAC[0], GATEWAY_MAC[1], GATEWAY_MAC[2], GATEWAY_MAC[3], GATEWAY_MAC[4], GATEWAY_MAC[5]);
}

void loop() {
  scan->start(SLOT_MS / 1000, false);   // 1초 BLE (블로킹)
  scan->clearResults();
  flush("BLE");
  ledBlinks = hotspotFound ? 1 : 3;     // 1초마다 (BLE 칸 끝)

  esp_wifi_set_promiscuous(true);       // 1초 Wi-Fi
  esp_wifi_set_channel(wifiCh, WIFI_SECOND_CHAN_NONE);
  delay(SLOT_MS);
  esp_wifi_set_promiscuous(false);
  flush("WIFI");
  ledBlinks = hotspotFound ? 1 : 3;     // 1초마다 (Wi-Fi 칸 끝)
}
