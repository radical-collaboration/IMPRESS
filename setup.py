from setuptools import setup, find_packages

setup(
    name='impress',
    version='0.1.0',
    description='IMPRESS protein binding prediction tools',
    author='Aymen',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    install_requires=['radical.flow'],
    python_requires='>=3.7',
)
