#!/bin/bash


set -e  # exit on error

echo "======================================"
echo "ECBS Standalone - Build and Test"
echo "======================================"
echo ""


echo "Checking dependencies..."

if ! command -v cmake &> /dev/null; then
    echo "Error: cmake not found. Please install CMake."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found."
    exit 1
fi


python3 -c "import pybind11" 2>/dev/null || {
    echo "Error: pybind11 not found. Installing..."
    pip3 install pybind11
}

echo "OK All dependencies found"
echo ""


echo "Installing Python package (development mode)..."
pip3 install -e .

echo ""
echo "OK Installation successful!"
echo ""


echo "Running Python tests..."
python3 tests/test_python.py

echo ""
echo "======================================"
echo "Build and test completed successfully!"
echo "======================================"
echo ""
echo "You can now use the module:"
echo "  python3 -c 'import ecbs_standalone as ecbs; print(ecbs.__version__)'"
echo ""
