# 추론 엔진 선택 보고서 — ONNX Runtime · NCNN · OpenVINO · LiteRT

- 작성자: 이수민
- 작성일: 2026-10-15
- 관련 문서: report/yolo_model.md (YOLO26n 선정·학습·검증), report/hardware.md (Raspberry Pi 4 사양)
- 결론: **NCNN**을 선택한다. ONNX Runtime은 예비 엔진으로 둔다. 최종 확정은 Raspberry Pi 4 실측으로 한다.

---

## 1. 추론 엔진이란

학습을 마친 YOLO26n 모델(`best.pt`)은 PyTorch 형식이라 그대로 쓰면 무겁고 느리다. 추론 엔진은 이 모델을 특정 장치에서 빠르게 돌아가도록 변환하고 실행해 주는 프로그램이다. 같은 모델이라도 어떤 엔진을 쓰느냐에 따라 속도, 파일 크기, 정확도가 달라진다. Ultralytics에서는 `yolo export model=best.pt format=ncnn`처럼 형식만 바꿔 각 엔진용 모델을 만들 수 있다.

---

## 2. 우리 제품의 조건

엔진은 PC가 아니라 **쓰레기통 안의 Raspberry Pi 4**에서 돈다. 이 장치의 CPU는 인텔이 아닌 **ARM(Cortex-A72, 64비트)**이고 GPU 가속이 없다. 인터넷 없이 동작해야 하고, 감지부터 안내까지 **2초 이내**(PRD KPI)에 끝나야 한다. 이 2초 안에 카메라 5장 촬영, 가장 선명한 프레임 고르기, 추론, 후처리, Arduino 명령 전송이 모두 들어가므로 추론 시간이 짧을수록 여유가 생긴다. 모델 파일은 10MB 이하가 목표다. 입력 크기는 YOLO 보고서에서 정한 대로 320×320이다.

---

## 3. 네 엔진의 특징

**ONNX Runtime**: Microsoft가 만든 범용 엔진이다. ONNX라는 공통 모델 형식을 거의 모든 운영체제와 CPU(인텔, AMD, ARM)에서 실행할 수 있고, Python에서 쓰기 쉽다. 특정 하드웨어에 특화되지 않은 대신 어디서나 무난하게 빠르다.

**OpenVINO**: Intel이 만든 엔진이다. 인텔 CPU, 내장 GPU, NPU에 맞춰 최적화되어 있어 인텔 PC에서 특히 빠르다. ARM CPU도 지원하지만 최적화의 중심은 인텔 하드웨어다.

**LiteRT (TFLite)**: Google이 만든 모바일·임베디드용 엔진으로, TensorFlow Lite의 새 이름이다. 스마트폰과 마이크로컨트롤러까지 지원하고, INT8 양자화(숫자를 작게 줄여 속도를 올리는 기술)가 잘 되어 있다. 다만 PyTorch 모델을 변환하는 과정이 여러 단계를 거쳐 복잡한 편이다.

**NCNN**: Tencent가 만든 모바일·ARM 전용 엔진이다. 처음부터 ARM CPU에서 빠르게 돌도록 설계되어 다른 라이브러리 의존이 적고 가볍다. Ultralytics 공식 문서도 Raspberry Pi에서는 NCNN 형식을 권장한다.

---

## 4. 비교 측정 결과 (참고: 인텔 PC)

수업에서 YOLO26n을 네 엔진으로 바꿔 같은 조건에서 비교했다. 측정 조건은 Intel Core Ultra 5 125H, 4스레드, 입력 640×640, FP32, COCO val2017 이미지 100장(정답 박스 709개)을 3번 반복한 것이다.

**ONNX Runtime**은 용량 9.94MB, 추론 p50 58.7ms, p95 69.0ms, 초당 15.3장, mAP50 63.77%로 이 PC에서 가장 빨랐다.
**OpenVINO**는 용량 10.13MB, 추론 p50 67.7ms, p95 85.8ms, 초당 13.6장, mAP50 63.77%였다. 실행할 때마다 편차가 커서 이전 실행에서는 57.8ms로 ONNX Runtime과 비슷했다.
**LiteRT**는 용량 10.27MB, 추론 p50 79.7ms, p95 85.1ms, 초당 11.7장, mAP50 63.77%였다.
**NCNN**은 용량 9.76MB로 가장 작았지만 추론 p50 87.7ms, p95 95.5ms, 초당 10.7장으로 이 PC에서는 가장 느렸고, mAP50은 62.87%로 0.9%p 낮았다(mAP50-95는 0.4%p 낮음).

ONNX Runtime, OpenVINO, LiteRT는 정확도가 소수점까지 같았다. NCNN만 정확도가 조금 낮은 이유는 엔진 성능이 아니라 출력 방식 차이다. NCNN이 top-k 연산을 지원하지 않아 YOLO26의 "NMS 불필요(end-to-end)" 출력이 꺼지고, 대신 일반적인 NMS(겹친 박스 정리) 후처리를 따로 하게 된다.

---

## 5. 결과를 우리 제품에 그대로 적용할 수 없는 이유

이 측정은 **인텔 x86 PC**에서 한 것이다. OpenVINO와 ONNX Runtime은 인텔 CPU에서 강하고, NCNN은 ARM CPU를 목표로 만든 엔진이라 인텔 PC에서는 제 실력이 나오지 않는다. 우리 장치인 Raspberry Pi 4는 ARM이라 순위가 달라질 가능성이 크다. 또 측정 입력은 640×640인데 우리는 320×320을 쓰므로 실제 추론 시간은 이보다 크게 짧아진다(계산량 약 4분의 1).

그래서 PC 결과는 "정확도 차이"와 "용량"을 확인하는 데 쓰고, 속도 순위는 Raspberry Pi 4에서 다시 측정해 확정한다.

---

## 6. 선택: NCNN

**첫째, 우리 장치(ARM)에 맞춰 만든 엔진이다.** NCNN은 ARM CPU의 병렬 연산 기능(NEON)을 직접 활용하도록 만들어졌고, Ultralytics도 Raspberry Pi에서 NCNN을 권장한다. 인텔 PC에서 가장 느렸던 결과는 ARM 전용 엔진을 인텔에서 돌린 결과라 우리 장치의 성능을 대표하지 않는다.

**둘째, 가장 작고 가볍다.** 모델 파일이 9.76MB로 네 엔진 중 가장 작아 10MB 목표를 만족하고, 실행에 필요한 라이브러리도 적어 Raspberry Pi의 메모리와 저장 공간 부담이 작다.

**셋째, 정확도 차이가 우리 제품에 영향을 줄 만큼 크지 않다.** PC 측정에서 mAP50이 0.9%p 낮았지만, 이는 COCO 80종 기준이고 우리 제품은 3종(페트병·캔·일반쓰레기)을 크게 찍어 구분하는 더 쉬운 문제다. 우리 데이터로 변환 전후 정확도를 비교해 하락이 2%p 이내인지 확인한다(합격 기준).

**대신 감수하는 점**: NCNN에서는 YOLO26의 NMS 없는 출력이 꺼져 일반 NMS 후처리가 들어간다. 우리 제품은 "박스가 2개 이상이면 하나씩 보여달라고 안내"하는 규칙이 있어, 같은 물체에 박스가 두 개 남으면 안 된다. Ultralytics로 NCNN 모델을 실행하면 NMS가 자동으로 적용되므로, 겹침 기준(IoU)을 0.5로 조금 엄격하게 두고 시험 데이터에서 중복 검출이 0건인지 확인한다.

---

## 7. 다른 엔진을 고르지 않은 이유

**ONNX Runtime (예비 엔진)**: 인텔 PC에서 가장 빨랐고 NMS 없는 출력도 그대로 유지되는 좋은 엔진이다. ARM에서도 동작하므로, Raspberry Pi 실측에서 NCNN보다 빠르거나 NCNN의 정확도 하락이 2%p를 넘으면 ONNX Runtime으로 바꾼다.

**OpenVINO**: 인텔 하드웨어에 최적화된 엔진이라 ARM인 Raspberry Pi에서는 장점을 살리기 어렵다. 나중에 인텔 기반 미니 PC로 바꾸는 경우에 다시 검토한다.

**LiteRT**: INT8 양자화로 ARM에서도 빠를 수 있지만, PyTorch → ONNX → TensorFlow → LiteRT로 이어지는 변환 단계가 많아 오류가 생기기 쉽고, PC 측정에서도 장점이 뚜렷하지 않았다. 처음 계획(PRD v0.3)에는 TFLite INT8을 적었으나 NCNN으로 바꾼다.

---

## 8. Raspberry Pi 4에서의 확정 방법

Raspberry Pi 4에서 같은 YOLO26n 모델을 네 엔진으로 변환해, 입력 320×320, 4스레드로 다음을 측정한다. 추론 시간 p50·p95, 초당 처리 장수, 모델 용량, 메모리 사용량, 우리 시험 데이터 기준 제품 안내 정확도와 중복 검출 수, 그리고 실행 중 CPU 온도와 속도 저하(throttling) 여부다.

```bash
# 엔진별로 변환
yolo export model=best.pt format=ncnn imgsz=320
yolo export model=best.pt format=onnx imgsz=320
yolo export model=best.pt format=openvino imgsz=320
yolo export model=best.pt format=tflite imgsz=320

# 한 번에 비교 (Ultralytics 벤치마크)
yolo benchmark model=best.pt data=data.yaml imgsz=320 device=cpu
```

선정 기준은 순서대로 합격 기준 충족(정확도 하락 2%p 이내, 중복 검출 0건), 감지부터 안내까지 95백분위 2초 이내, 추론 p95가 가장 짧은 엔진이다. 측정 결과는 이 보고서와 홈페이지에 추가한다.

---

## 9. 다른 문서에 반영할 점

PRD v0.3 기술 스택의 "추론 런타임: TensorFlow Lite INT8"을 "NCNN (예비: ONNX Runtime)"으로 바꾼다. YOLO 보고서의 NMS-free 장점 설명에는 "NCNN에서는 NMS 후처리가 추가된다"는 점을 덧붙인다.
