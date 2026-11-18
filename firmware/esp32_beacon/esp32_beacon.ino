/*
  ExamSentry 보정·복도 통행용 BLE 비콘 (예비 ESP32 1대)
  ※ 아직 실기 테스트 전.

  - 보정: 이 보드를 각 구역에 놓고 stage_log.py 로 라벨을 남긴다.
  - 시연: 팀원이 들고 복도를 지나가는 '통행 신호' 역할.
  - 시리얼 모니터(115200)에 자기 MAC을 계속 출력 → stage_log.py --id 에 넣는다.
*/
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEAdvertising.h>

void setup() {
  Serial.begin(115200);
  BLEDevice::init("ES-BEACON");
  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->setMinInterval(0x00A0);   // 100ms
  adv->setMaxInterval(0x00A0);
  adv->start();
}

void loop() {
  Serial.printf("BEACON MAC %s\n", BLEDevice::getAddress().toString().c_str());
  delay(3000);
}
