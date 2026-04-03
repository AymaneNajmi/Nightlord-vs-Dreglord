# Backend

## Hardware Cisco

## Installation

```bash
pip install -r requirements.txt
```

### Debug JSON (exemple)

```bash
curl -X POST http://localhost:8000/api/hardware/debug \\
  -H "Authorization: Bearer <token>" \\
  -H "Content-Type: application/json" \\
  -d '{"hardware_reference":"C9200L-24T-4X-E"}'
```
