#!/bin/bash

while :
do
	python3 /app/runner_notify.py -c /config/config.ini
	sleep 60
done
	
