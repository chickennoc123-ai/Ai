#!/bin/bash
# ---------------------------------------------------------------------------
# EA Factory Pro - InfluxDB bootstrap.
# Creates the buckets used by the platform beyond the default one.
# ---------------------------------------------------------------------------
set -euo pipefail

ORG="${DOCKER_INFLUXDB_INIT_ORG:-ea-factory}"
TOKEN="${DOCKER_INFLUXDB_INIT_ADMIN_TOKEN:-ea-factory-dev-token}"

create_bucket() {
    local name="$1"
    local retention="$2"
    if influx bucket list --org "$ORG" --token "$TOKEN" | grep -qw "$name"; then
        echo "Bucket '$name' already exists"
    else
        influx bucket create --name "$name" --org "$ORG" --token "$TOKEN" --retention "$retention"
        echo "Created bucket '$name' (retention $retention)"
    fi
}

# market  : ticks and OHLCV               - 90 days
# metrics : platform and strategy metrics - 365 days
create_bucket "market" "90d"
create_bucket "metrics" "365d"

echo "InfluxDB bootstrap complete."
