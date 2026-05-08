#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name="etf-cli",
    version="0.1.0",
    description="Real-time A-share ETF quotes CLI for AI analysis",
    author="Claude",
    py_modules=["etf"],
    install_requires=[
        "click>=8.0.0",
        "requests>=2.25.0",
    ],
    entry_points={
        "console_scripts": [
            "etf=etf:cli",
        ],
    },
    python_requires=">=3.8",
)
