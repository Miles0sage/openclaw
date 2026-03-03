#!/bin/sh
cd /root/openclaw
python3 -m pytest test_n8n_webhook.py --tb=short -v > /root/openclaw/test_results.txt 2>&1
echo "Exit code: $?" >> /root/openclaw/test_results.txt
