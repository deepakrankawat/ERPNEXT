# Production compliance gates

The application fails closed when the following production dependencies are
not configured. Release management must attach evidence for each item before a
production go-live.

| Gate | Required evidence |
| --- | --- |
| Malware scanning | Supported ClamAV installed, signatures updated, clean/EICAR/unavailable tests recorded |
| Payment webhook | Secret stored outside source control, valid/invalid/replay tests recorded |
| AI gateway | Controlled gateway URL and secret, retention owner, retry/circuit and kill-switch drill recorded |
| Backups and recovery | Encrypted backup, restore test, measured RPO/RTO, audit-chain verification after restore |
| Availability | Web, workers, scheduler, Redis/Socket.IO, MariaDB monitoring and alert routes tested |
| Performance | Representative portal/chat/ledger workload, percentile latency, error-rate and saturation report |
| Accessibility | Keyboard, focus, labels, contrast, zoom/reflow and screen-reader review of client workflows |
| Security | Dependency/SAST/DAST results, tenant-isolation regression, session and secret-rotation checks |

The automated app suite validates functional and authorization behavior. It is
not a substitute for infrastructure load, disaster-recovery, penetration, or
formal accessibility evidence.
