from setuptools import setup, find_packages

setup(
    name="NotosDiskAnalyzer",
    version="1.0.0",
    description="A cross-platform disk space analysis tool",
    packages=find_packages(),
    install_requires=[
        "PyQt5>=5.15.0",
        "matplotlib>=3.5.0",
        "psutil>=5.9.0",
    ],
    entry_points={
        'console_scripts': [
            'diskspace-analyzer=main:main',
        ],
    },
)
