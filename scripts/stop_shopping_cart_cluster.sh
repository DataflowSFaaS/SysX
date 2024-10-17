#!/bin/bash

./scripts/stop_sysx_cluster.sh

docker compose -f docker-compose-shopping-cart-demo.yml down --volumes --remove-orphans
