# ML-001 + AGLE 24/7 Production Deployment Guide

**Date**: August 17, 2026  
**Status**: 🟢 READY FOR DEPLOYMENT  
**Objective**: Deploy ML-001 (EURUSD, GBPUSD) + AGLE continuous monitoring

---

## Overview

This guide covers deploying two complementary systems:

1. **ML-001 Production** (EURUSD, GBPUSD): ML-driven automated trading with health monitoring
2. **AGLE 24/7**: Continuous market monitoring and AI-assisted analysis

Both systems run simultaneously with:
- Separate resource allocation (no conflicts)
- Independent health monitoring
- Combined audit trail
- Unified reporting

---

## System Requirements

### For ML-001 Production (Local/Remote)
- Python 3.9+
- Core modules: ML001Adapter, RiskGovernance, DecisionRegistry
- Memory: ~500MB
- CPU: 1 core minimum
- No external dependencies

### For AGLE 24/7 (Docker-based)
- Docker Engine 20.10+
- Docker Compose 2.0+
- Memory: ~2GB (6 containers)
- CPU: 2+ cores
- Network: 5 ports (5432, 6379, 8086, 8000, 8501)

---

## Pre-Deployment Checklist

- ✅ ML-001 batch staging complete (2/5 approved)
- ✅ All thresholds met
- ✅ IA-001 audit passed
- ✅ 303 tests passing
- ✅ Production code committed
- ✅ AGLE docker-compose.yml available
- ✅ Environment configured

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────┐
│         Production Orchestrator                         │
│  (ml_001_agle_production_orchestrator.py)              │
└────────────────┬────────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
   ML-001 Production   AGLE 24/7
   ┌─────────────┐    ┌──────────────┐
   │ ProductionRunner
   │ HealthMonitor
   │ RiskGovernance
   │
   │ EURUSD (7.2%)
   │ GBPUSD (7.2%)
   └─────────────┘    │ Docker Compose
                      │ API (8000)
                      │ Dashboard (8501)
                      │ Worker (agents)
                      │ PostgreSQL (5432)
                      │ Redis (6379)
                      │ InfluxDB (8086)
                      └──────────────┘

Data Flow:
  Market Data → ML-001 Signals → Execution → P&L Tracking
           ↓
           AGLE Monitor → Analysis → Alerts
```

---

## Deployment Steps

### Step 1: Verify Environment

```bash
# Check Python
python --version  # 3.9+

# Check Docker (if using AGLE)
docker --version
docker-compose --version

# Check ports are available
netstat -ano | grep -E ":8000|:8501|:5432|:6379|:8086"
```

### Step 2: Start Production Orchestrator

```bash
# Run orchestrator (manages both systems)
python ml_001_agle_production_orchestrator.py

# Or run in background with nohup
nohup python ml_001_agle_production_orchestrator.py > production.log 2>&1 &

# Or run with systemd (for permanent 24/7)
# See: systemd-service-setup.md
```

### Step 3: Verify Both Systems Running

```bash
# Monitor ML-001
tail -f logs/orchestrator.log

# Check ML-001 (separate terminal)
ps aux | grep ml_001_production

# Check AGLE (if Docker available)
docker-compose ps

# Verify ports
curl http://localhost:8000/docs  # AGLE API
curl http://localhost:8501       # AGLE Dashboard
```

### Step 4: Monitor Production

```bash
# Real-time logs
tail -f logs/orchestrator.log | grep "STATUS\|WARNING\|CRITICAL"

# Check P&L updates (every 60 ticks)
grep "Status (Tick" logs/orchestrator.log | tail -10

# Check for alerts
grep "WARNING\|CRITICAL" logs/orchestrator.log
```

---

## Configuration Reference

### ML-001 Configuration

| Parameter | Value | Notes |
|-----------|-------|-------|
| EURUSD Allocation | 7.2% ($720) | Approved from staging |
| GBPUSD Allocation | 7.2% ($720) | Approved from staging |
| Total Allocation | 14.4% ($1,440) | Well within limits |
| Max Positions/Symbol | 3 | Risk limit |
| Max Total Positions | 6 | Portfolio limit |
| Max Drawdown | 15% | Hard stop |
| Max Daily Loss | $100 | Hard stop |
| Monitor Interval | 60 seconds | Health checks |
| Status Updates | Every 60 ticks | Logging |

### AGLE Configuration

| Parameter | Value | Notes |
|-----------|-------|-------|
| Services | 6 containers | API, Worker, Dashboard, PostgreSQL, Redis, InfluxDB |
| Auto-restart | Enabled | unless-stopped policy |
| API Port | 8000 | http://localhost:8000 |
| Dashboard Port | 8501 | http://localhost:8501 |
| Database Port | 5432 | PostgreSQL |
| Cache Port | 6379 | Redis |
| Time Series Port | 8086 | InfluxDB |
| Symbols Monitored | All 5 | EURUSD, GBPUSD, XAUUSD, USDJPY, AUDUSD |

---

## Operational Procedures

### Starting Production

#### Option 1: Interactive (Foreground)
```bash
python ml_001_agle_production_orchestrator.py
```

#### Option 2: Background (nohup)
```bash
nohup python ml_001_agle_production_orchestrator.py > logs/production.log 2>&1 &
echo $! > production.pid
```

#### Option 3: Systemd (Permanent 24/7)
```bash
# Create service file
sudo tee /etc/systemd/system/ml-001-agle.service > /dev/null <<EOF
[Unit]
Description=ML-001 + AGLE Production
After=network.target docker.service

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/user/Ai
ExecStart=/usr/bin/python3 ml_001_agle_production_orchestrator.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl enable ml-001-agle.service
sudo systemctl start ml-001-agle.service

# Check status
sudo systemctl status ml-001-agle.service
```

### Monitoring Production

```bash
# Real-time monitoring
tail -f logs/orchestrator.log

# Search for status updates
grep "Status" logs/orchestrator.log | tail -20

# Search for alerts
grep "WARNING\|CRITICAL" logs/orchestrator.log

# Check running processes
ps aux | grep "ml_001\|docker"

# Check Docker (if using AGLE)
docker-compose ps
docker-compose logs -f --tail=50
```

### Emergency Stop

```bash
# Method 1: Ctrl+C (graceful)
# Press Ctrl+C in foreground terminal

# Method 2: Kill process (if background)
kill $(cat production.pid)

# Method 3: Systemd
sudo systemctl stop ml-001-agle.service

# Verify stopped
ps aux | grep ml_001_production
docker-compose ps
```

### Viewing Reports

```bash
# ML-001 production report
cat reports/production/production_report_*.json | jq .

# AGLE logs
docker logs eafactory-worker --tail 100

# Performance summary
grep "Status" logs/orchestrator.log | tail -1
```

---

## Troubleshooting

### Issue: "Docker not available"

**Cause**: Docker daemon not running or not installed

**Solution**:
1. Install Docker: https://docs.docker.com/get-docker/
2. Start Docker daemon: `sudo systemctl start docker`
3. Run orchestrator again

**Note**: ML-001 will still run even without Docker/AGLE

### Issue: "Port already in use"

**Cause**: Another service using ports 8000, 8501, 5432, 6379, 8086

**Solution**:
```bash
# Find what's using port
lsof -i :8000
lsof -i :8501

# Kill process
kill <PID>

# Or change AGLE ports in docker-compose.yml
```

### Issue: "ML-001 not generating signals"

**Cause**: Strategy initialization failed or market data unavailable

**Solution**:
1. Check logs: `tail logs/orchestrator.log`
2. Verify adapters loaded: grep "✅" logs/orchestrator.log
3. Restart orchestrator

### Issue: "Memory usage increasing"

**Cause**: Memory leak or too many positions open

**Solution**:
1. Check positions: grep "Status" logs/orchestrator.log | tail -1
2. If > 6 positions total, emergency stop triggered
3. Check for error logs

### Issue: "AGLE containers crashing"

**Cause**: Insufficient resources or configuration error

**Solution**:
```bash
# Check container logs
docker logs eafactory-worker --tail 100
docker logs eafactory-api --tail 100

# Restart containers
docker-compose restart

# Check resource limits
docker stats --no-stream
```

---

## Performance Monitoring

### Key Metrics

| Metric | Expected | Alert Level |
|--------|----------|-------------|
| ML-001 P&L | Variable | Drawdown > 15% |
| Total Positions | ≤6 | > 6 |
| Daily Loss | < $100 | ≥ $100 |
| Health Check | Pass | Fail |
| AGLE API Response | < 1s | > 5s |

### Monitoring Commands

```bash
# ML-001 P&L
grep "Status" logs/orchestrator.log | tail -5

# AGLE container health
docker-compose ps

# Resource usage
docker stats --no-stream
ps aux | grep ml_001

# API health
curl http://localhost:8000/health
curl http://localhost:8501
```

---

## Database & Persistence

### ML-001 Storage
- Logs: `logs/orchestrator.log`
- Reports: `reports/production/production_report_*.json`
- Decision Registry: In-memory (session-based)

### AGLE Storage
- PostgreSQL: `/var/lib/postgresql/data` (Docker volume)
- Redis: `/data` (Docker volume)
- InfluxDB: `/var/lib/influxdb2` (Docker volume)

### Backup Procedures

```bash
# Backup reports
cp reports/production/*.json reports/backups/

# Backup AGLE database
docker exec eafactory-postgres pg_dump -U eafactory eafactory > backup.sql

# Backup all volumes
docker-compose exec postgres pg_dump -U eafactory eafactory > eafactory_backup.sql
```

---

## Security Considerations

1. **API Access**: AGLE API (8000) is exposed - consider firewall rules
2. **Database Credentials**: Use strong passwords in .env
3. **Logs**: May contain sensitive trading data - restrict access
4. **Backups**: Encrypt database backups before storage
5. **Network**: Deploy with VPN or private network for production

---

## 24/7 Operational Checklist

### Daily
- [ ] Check P&L updates
- [ ] Review alert logs
- [ ] Verify both systems running
- [ ] Monitor drawdown/daily loss

### Weekly
- [ ] Review performance reports
- [ ] Check database size (PostgreSQL)
- [ ] Verify backups completed
- [ ] Monitor resource usage

### Monthly
- [ ] Analyze strategy performance
- [ ] Review rejected symbols for improvement
- [ ] Update risk parameters if needed
- [ ] Archive old logs/reports

---

## Scaling & Future Enhancements

### Short Term
1. Monitor approved strategies (EURUSD, GBPUSD)
2. Collect live performance data
3. Verify risk management effective

### Medium Term (30-60 days)
1. Iterate on rejected symbols (XAUUSD, USDJPY, AUDUSD)
2. Consider additional symbol pairs
3. Optimize feature engineering

### Long Term (60+ days)
1. Expand to more symbols
2. Increase allocation if performance strong
3. Add additional strategies
4. Integrate with live broker (currently simulated/demo)

---

## Support & Resources

### Documentation
- ML-001 Reports: `ML-001-*.md`
- AGLE Docs: `docker-compose.yml`, `.env.example`
- Architecture: `CONSTITUTION.md`

### Logs & Monitoring
- Production: `logs/orchestrator.log`
- AGLE API: http://localhost:8000/docs
- AGLE Dashboard: http://localhost:8501

### Emergency Contact
- Health Monitor: Active (automatic stops on thresholds)
- Emergency Stop: Triggered at DD > 15% or Loss > $100
- Manual Stop: Ctrl+C or `kill` process

---

## Conclusion

ML-001 + AGLE 24/7 production deployment provides:

✅ Automated ML-driven trading (2 approved strategies)
✅ Continuous market monitoring (AGLE)
✅ Real-time health monitoring
✅ Emergency stop protection
✅ Full audit trail and reporting
✅ 24/7 operation capability

**Status**: 🟢 **READY FOR PRODUCTION**

**Next Step**: Execute `python ml_001_agle_production_orchestrator.py`

---

**Document Version**: 1.0  
**Last Updated**: August 17, 2026  
**Status**: Production Ready

