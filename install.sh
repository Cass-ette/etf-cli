#!/bin/bash
# Install etf-cli tool

set -e

echo "Installing etf-cli..."

# Check if pip3 is available
if ! command -v pip3 &> /dev/null; then
    echo "Error: pip3 not found. Please install Python 3."
    exit 1
fi

# Install dependencies
pip3 install -r requirements.txt

# Install the CLI
pip3 install -e .

echo ""
echo "✓ etf-cli installed successfully!"
echo ""
echo "Quick start:"
echo "  etf get 562500          # 查单只ETF"
echo "  etf get 562500 --json   # JSON输出（给AI）"
echo "  etf get 562500 --ai     # Markdown输出（给AI）"
echo "  etf add 562500          # 加入自选"
echo "  etf list                # 查看自选列表"
echo "  etf watch               # 自选AI格式输出"
echo ""
