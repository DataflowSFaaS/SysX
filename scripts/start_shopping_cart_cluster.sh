#!/bin/bash

./scripts/start_sysx_cluster.sh 4 100

docker compose -f docker-compose-shopping-cart-demo.yml up --build