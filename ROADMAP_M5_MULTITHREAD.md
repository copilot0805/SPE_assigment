# M5 ? ??nh gi? Hi?u n?ng 3 Ki?n tr?c Th?c thi M? ph?ng DES (Nh?nh `multithread_dev`)

T?i li?u t?ng k?t to?n b? ki?n tr?c, ph??ng ph?p lu?n 10 b??c ??nh gi? Hi?u n?ng H? th?ng (SPE), s? li?u th?c ?o 1-core v? h??ng d?n t?i l?p cho **M?c M5** c?a nh?m **SPE-L0x-008** (CO3007 ? ?H B?ch Khoa TP.HCM).

---

## 1. Ph?m vi & Nguy?n t?c K? thu?t
* **Kh?ng ch?nh s?a th? m?c `bkitevsim/`:** To?n b? 5 l?i c?a framework g?c (LadderQueue wrap-around, `create_lp` l?c `end_time` & `create_lps` ghi ?? ID 0, `wait_for()` b? s?t `_pending_events`, `_process_events_at_current_time()` nu?t Exception, circular import `queues`/`core`) ??u ???c h?a gi?i ? t?ng tr?n trong `drivethru/engines/`.
* **T?ch nh?nh an to?n:** Nh?nh `multithread_dev` r? t? nh?nh ?n ??nh `sequential_dev` (M1?M4), gi? nguy?n 100% logic nghi?p v? trong `drivethru/core/`, `drivethru/models/`, `drivethru/metrics/`.
* **Ba ki?n tr?c th?c thi so s?nh tr?c ti?p tr?n c?ng m?ng Drive-thru 4 tr?m (6 LP):**
  1. **Single-thread (`drivethru/engines/sequential_engine.py`):** `SequentialEventDispatcher` + `BkSysLogicalProcess` (1 OS thread, g?i h?m ??ng b? `handle_event()`).
  2. **Virtual Multi-thread (`drivethru/engines/coroutine_engine.py`):** `BkSysCoEventLoop` + `SafeCoLogicalProcess` + **`BkSysFuture` t?i b?ng Join c?a `CoPickupLP`** (1 OS thread, ?a nhi?m h?p t?c `async/await`).
  3. **OS Multi-thread (`drivethru/engines/multithread_engine.py`):** 6 `threading.Thread` th?t cho 6 LP (`LP0..LP5`) + `ThreadedClockCoordinator` ??ng b? b?o th? theo t?ng m?c th?i gian nh? nh?t $t_{min}$ b?ng `LadderQueue` v? `threading.Condition` (0 causality error, 0 deadlock).

---

## 2. Thi?t k? Th? nghi?m M5 theo 10 B??c ??nh gi? Hi?u n?ng (SPE)

| B??c PE | N?i dung tri?n khai t?i M5 |
|---|---|
| **1. Goals & SUT** | So s?nh t?c ?? th?c thi, t?i nguy?n ph?n c?ng v? ?? to?n v?n k?t qu? c?a 3 ki?n tr?c DES. SUT = Engine th?c thi m?ng Drive-thru 4 tr?m (6 LP + h?ng ??i s? ki?n + ?i?u ph?i) tr?n **Windows 11, CPU 4-core/8-thread, CPython 3.12.10 (c? GIL)**. |
| **2. Services & Outcomes** | D?ch v? = th?c thi tr?n v?n 1 l??t m? ph?ng $[0, t_{end}]$ b?o to?n nh?n qu?. 3 k?t qu?: (i) ??ng ? kh?p b?n chu?n; (ii) Sai ? causality error/race condition; (iii) Kh?ng l?m ???c ? Deadlock/Crash. |
| **3. Metrics** | Wall-clock Time (s, LB), Event Throughput (events/sec, HB), CPU Time & t? s? CPU/Wall (LB), Peak Python Heap Memory (MB, LB), Fidelity Error (sai l?ch max tr?n 10 ch? s? c?t l?i, b?t bu?c $< 10^{-9}$), Deadlock & Causality Error Rate (b?t bu?c = 0%). |
| **4. Parameters** | C? ??nh: c?u h?nh t?i ?u M4 ($c_1=c_2=c_3=c_4=2, K_1=6$), $\lambda = 0.6$ (Peak), $t_{warmup} = 500$ ph?t, `safe_bucket_width(t_end)`. |
| **5. Factors & Levels** | **Factor A ? Ki?n tr?c (3 m?c):** `sequential`, `coroutine`, `multithread`. **Factor B ? Quy m? $t_{end}$ (3 m?c):** 2 000, 5 000, 10 000 ph?t (t??ng ?ng ~17.6k, ~44.3k, ~89.2k s? ki?n). |
| **6. Technique** | **Measurement** tr?c ti?p tr?n ch??ng tr?nh th?t k?t h?p **Cross-validation** c?ng seed v?i b?n chu?n `sequential`. |
| **7. Workload** | C?ng d?ng s? ki?n sinh t? `MultiStreamRNG` (5 lu?ng CRN) v?i `seed = 1..10` ?? c? 3 engine x? l? s? s? ki?n gi?ng h?t nhau. |
| **8. Experimental Design** | Giai th?a ??y ?? $3 \times 3 = 9$ c?u h?nh $\times R=10$ seeds (+ 1 l??t warm-up `seed=999` b? ?i). **?o tu?n t? ??n ti?n tr?nh (1 core)**, kh?ng d?ng `ProcessPoolExecutor`. T?ch ri?ng Pha 1 (`tracemalloc` t?t -> ?o `wall_time`/`cpu_time` s?ch observer effect) v? Pha 2 (`tracemalloc` b?t tr?n 3 seeds -> ?o `peak_mem_mb`). |
| **9. Analyze & Interpret** | Mean ? CI 95% (Student-$t$, $t_{0.975,9}=2.2622$), Slowdown Ratio so v?i Single-thread, ph?n r? chi ph? Coroutine frame vs. GIL + Condition barrier. |
| **10. Present Results** | B?ng `reports/exp_m5_benchmark.csv` v? 2 bi?u ?? `reports/fig6_m5_walltime_throughput.png`, `reports/fig7_m5_memory_and_overhead.png`. |

---

## 3. K?t qu? Th?c ?o (1-Core, CPython 3.12.10 GIL)

Tr?ch t? `reports/exp_m5_benchmark.csv` (90/90 l??t Timing PASS fidelity $< 10^{-9}$, 0 causality error, 0 deadlock):

| Engine | $t_{end}$ (ph?t) | Events (TB) | Wall Time (s) ? CI 95% | Slowdown | Throughput (ev/s) | CPU/Wall | Peak Mem (MB) | Max Fidelity Err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **sequential** | 2 000 | 17 633 | `0.3222 ? 0.0475` | **1.00x** | 56 633 | 0.975 | 0.109 | `0.0e+00` |
| **coroutine** | 2 000 | 17 633 | `0.7449 ? 0.0799` | **2.31x** | 24 087 | 0.988 | 0.136 | `0.0e+00` |
| **multithread** | 2 000 | 17 633 | `1.1559 ? 0.0811` | **3.59x** | 15 379 | 0.962 | 0.134 | `0.0e+00` |
| **sequential** | 5 000 | 44 258 | `0.6906 ? 0.0560` | **1.00x** | 64 800 | 0.976 | 0.239 | `0.0e+00` |
| **coroutine** | 5 000 | 44 258 | `1.7512 ? 0.1088` | **2.54x** | 25 418 | 0.983 | 0.255 | `0.0e+00` |
| **multithread** | 5 000 | 44 258 | `3.1330 ? 0.0986` | **4.54x** | 14 154 | 0.958 | 0.262 | `0.0e+00` |
| **sequential** | 10 000 | 89 157 | `1.2857 ? 0.0725` | **1.00x** | 69 726 | 0.986 | 0.451 | `0.0e+00` |
| **coroutine** | 10 000 | 89 157 | `3.3657 ? 0.1046` | **2.62x** | 26 529 | 0.990 | 0.468 | `0.0e+00` |
| **multithread** | 10 000 | 89 157 | `6.3266 ? 0.1306` | **4.92x** | 14 102 | 0.954 | 0.475 | `0.0e+00` |

---

## 4. Ph?n t?ch & Di?n gi?i K? thu?t (B??c 9 PE)
1. **?? to?n v?n tuy?t ??i (Fidelity = 0.0):** Tr?n c? 3 quy m? ($t_{end} = 2000 \to 10000$) v? c? 2 ch? ?? Non-blocking / Blocking, sai l?ch c?c ??i gi?a 3 ki?n tr?c b?ng `0.0e+00` tr?n to?n b? 10 ch? s? (`T, P_b, U1..U4, W_f, X, P95_T, L_system`). Th?i gian ?o v? k?t qu? m? h?nh h?ng ??i ho?n to?n b?t bi?n theo ki?n tr?c th?c thi.
2. **Th? b?c t?c ?? th?c t?:** $\text{Wall(Single)} < \text{Wall(Virtual/Coroutine)} \ll \text{Wall(OS-Thread)}$ ? m?i quy m?.
   * **Single-thread (`69.7k ev/s`, `1.00x`):** M?i s? ki?n ch? l? m?t l?i g?i h?m `handle_event()` tr?c ti?p tr?n 1 lu?ng, kh?ng c? chi ph? khung coroutine hay ??ng b? lu?ng.
   * **Virtual Multi-thread (`26.5k ev/s`, `2.62x`):** Ch?m h?n ch? y?u do chi ph? ? t?ng ng??i d?ng (`CPU/Wall = 0.990`): kh?i t?o `BkSysFuture` + `asyncio.Task` t?i b?ng Join c?a `CoPickupLP` v? v?ng nh??ng quy?n `await asyncio.sleep(0)` trong `BkSysCoEventLoop._run_async()`. Tuy nhi?n, v?n nhanh g?n **g?p ??i** OS Multi-thread.
   * **OS Multi-thread (`14.1k ev/s`, `4.92x`):** Ch?m nh?t v? h? s? slowdown t?ng d?n theo quy m? (`3.59x` -> `4.54x` -> `4.92x`) v? 3 nguy?n nh?n c?ng h??ng: (i) **CPython 3.12 GIL** tu?n t? h?a th?c thi bytecode c?a 6 lu?ng; (ii) **?? h?t s? ki?n si?u nh?** (v?i micro-gi?y/s? ki?n) khi?n chi ph? ??ng b? `threading.Condition` barrier + chuy?n ng? c?nh nh?n Windows l?n h?n nhi?u l?n chi ph? t?nh to?n s? ki?n; (iii) t? s? `CPU/Wall` gi?m xu?ng `0.954` ph?n ?nh th?i gian lu?ng ng? ch? kh?a/t?n hi?u ??ng b?.
3. **D?u ch?n b? nh? (RAM):** C? 3 ki?n tr?c ??u g?n nh? (< 0.5 MB Python heap t?i $t_{end}=10000$, ch? y?u l?u m?u `t_samples` ? `MonitorLP`); Coroutine v? OS Multi-thread ch? t?ng th?m kho?ng `0.017?0.024 MB` so v?i Single-thread.
4. **Khuy?n ngh? ki?n tr?c DES tr?n Python:** D?ng **Single-thread Sequential** cho chi?n d?ch ch?y h?ng ngh?n k?ch b?n (k?t h?p `ProcessPoolExecutor` ? t?ng ngo?i ?? song song h?a theo seed ??c l?p nh? M4); d?ng **Virtual Multi-thread (Coroutine)** khi c?n bi?u di?n t??ng minh lu?ng ti?n tr?nh/future b?t ??ng b?; **kh?ng** d?ng OS `threading.Thread` ?? song song h?a n?i b? c?c LP c? t?c v? nh? tr?n CPython c? GIL.

---

## 5. L?nh T?i l?p cho Examiner (Windows PowerShell)
```powershell
# 1. Chuy?n sang nh?nh M5
git checkout multithread_dev

# 2. Ch?y tr?n b? 17 unit tests (M1 + M2 + M3 + M5)
python -m unittest discover -s tests -p "test_m*.py" -v

# 3. Ch?y l?i Benchmark 1-core (x?a CSV c? trong reports/ n?u mu?n ?o m?i ho?n to?n)
python -m drivethru.experiments.run_m5_benchmark

# 4. V? l?i 2 bi?u ?? M5 (fig6 & fig7)
python -m drivethru.experiments.plot_m5_benchmark
```
