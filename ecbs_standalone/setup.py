#!/usr/bin/env python3
"""
ECBS Standalone - Setup script for building Python bindings
"""

import os
import sys
import subprocess
from pathlib import Path

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext


class CMakeExtension(Extension):
    """Custom extension built with CMake"""
    def __init__(self, name, sourcedir=''):
        Extension.__init__(self, name, sources=[])
        self.sourcedir = os.path.abspath(sourcedir)


class CMakeBuild(build_ext):
    """Custom build_ext command using CMake"""

    def build_extension(self, ext):
        extdir = os.path.abspath(os.path.dirname(self.get_ext_fullpath(ext.name)))

        # CMake configuration arguments
        cmake_args = [
            f'-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={extdir}',
            f'-DPYTHON_EXECUTABLE={sys.executable}',
            '-DBUILD_PYTHON_BINDINGS=ON',
            '-DBUILD_TESTS=OFF',
        ]

        # Build type
        cfg = 'Debug' if self.debug else 'Release'
        build_args = ['--config', cfg]

        cmake_args += [f'-DCMAKE_BUILD_TYPE={cfg}']

        # Parallel build
        if sys.platform.startswith('darwin') or sys.platform.startswith('linux'):
            import multiprocessing
            build_args += ['--', f'-j{multiprocessing.cpu_count()}']

        env = os.environ.copy()
        env['CXXFLAGS'] = f"{env.get('CXXFLAGS', '')} -DVERSION_INFO=\\\"{self.distribution.get_version()}\\\""

        # Create build directory
        if not os.path.exists(self.build_temp):
            os.makedirs(self.build_temp)

        # Configure CMake
        print(f"Running CMake configuration in {self.build_temp}")
        subprocess.check_call(
            ['cmake', ext.sourcedir] + cmake_args,
            cwd=self.build_temp,
            env=env
        )

        # Build with CMake
        print(f"Building extension {ext.name}")
        subprocess.check_call(
            ['cmake', '--build', '.'] + build_args,
            cwd=self.build_temp
        )

        # Copy the built extension
        import shutil
        import glob

        # Destination directory
        build_lib_dir = os.path.dirname(self.get_ext_fullpath(ext.name))
        os.makedirs(build_lib_dir, exist_ok=True)

        # Determine the extension suffix
        import sysconfig
        ext_suffix = sysconfig.get_config_var('EXT_SUFFIX') or sysconfig.get_config_var('SO')
        if not ext_suffix:
            if sys.platform.startswith('win'):
                ext_suffix = '.pyd'
            else:
                ext_suffix = '.so'

        # Built filename
        module_name = f"ecbs_standalone{ext_suffix}"

        # Candidate output locations
        search_dirs = [
            extdir,  # CMake output directory
            ext.sourcedir,  # Source directory
            self.build_temp,  # Temporary build directory
        ]

        found = False
        for search_dir in search_dirs:
            output_file = os.path.join(search_dir, module_name)
            if os.path.isfile(output_file):
                dest_file = os.path.join(build_lib_dir, module_name)
                # Check whether source and destination are identical
                if os.path.abspath(output_file) != os.path.abspath(dest_file):
                    print(f"Copying {output_file} to {dest_file}")
                    shutil.copy2(output_file, dest_file)
                else:
                    print(f"Output file already in correct location: {output_file}")
                found = True
                break

            # Try glob matching to handle suffixes
            pattern = os.path.join(search_dir, f"ecbs_standalone{ext_suffix.split('.')[0]}.*")
            for match_file in glob.glob(pattern):
                if os.path.isfile(match_file):
                    dest_file = os.path.join(build_lib_dir, os.path.basename(match_file))
                    # Check whether source and destination are identical
                    if os.path.abspath(match_file) != os.path.abspath(dest_file):
                        print(f"Copying {match_file} to {dest_file}")
                        shutil.copy2(match_file, dest_file)
                    else:
                        print(f"Output file already in correct location: {match_file}")
                    found = True
                    break
            if found:
                break

        if not found:
            # List all candidate files
            print(f"Searching for extension files...")
            for search_dir in search_dirs:
                print(f"  Checking {search_dir}")
                if os.path.exists(search_dir):
                    for file in os.listdir(search_dir):
                        if 'ecbs_standalone' in file and (file.endswith('.so') or file.endswith('.pyd')):
                            output_file = os.path.join(search_dir, file)
                            dest_file = os.path.join(build_lib_dir, file)
                            # Check whether source and destination are identical
                            if os.path.abspath(output_file) != os.path.abspath(dest_file):
                                print(f"Found and copying {output_file} to {dest_file}")
                                shutil.copy2(output_file, dest_file)
                            else:
                                print(f"Found output file already in correct location: {output_file}")
                            found = True
                            break
                if found:
                    break

        if not found:
            raise RuntimeError(
                f"Could not find built extension for {ext.name}. "
                f"Searched in: {', '.join(search_dirs)}"
            )


# Read README
readme_file = Path(__file__).parent / 'README.md'
long_description = ''
if readme_file.exists():
    with open(readme_file, 'r', encoding='utf-8') as f:
        long_description = f.read()
else:
    long_description = 'ECBS (Enhanced Conflict-Based Search) C++ implementation with Python bindings'


setup(
    name='ecbs-standalone',
    version='1.0.0',
    description='High-performance ECBS implementation in C++ with Python bindings',
    long_description=long_description,
    long_description_content_type='text/markdown',

    ext_modules=[CMakeExtension('ecbs_standalone')],
    cmdclass={'build_ext': CMakeBuild},

    zip_safe=False,
    python_requires='>=3.9',

    # dependencies are now in pyproject.toml

    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'Topic :: Scientific/Engineering :: Artificial Intelligence',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: C++',
    ],

    keywords='ecbs mapf multi-agent path-finding conflict-based-search',
)
