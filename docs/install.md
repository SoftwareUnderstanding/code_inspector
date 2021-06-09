## Dependencies:

code_inpsector uses [abstract syntax trees (ASTs)](https://en.wikipedia.org/wiki/Abstract_syntax_tree), more specifically
the [ast](https://docs.python.org/3/library/ast.html) module in Python, generating a tree of objects (per file) whose classes all inherit from [ast.AST](https://docs.python.org/3/library/ast.html#ast.AST).

code_inspector parses each of the input file(s) as an ast tree, and walks across them, extracting
the relevant information, storing it as a JSON file.  Furthermore, it also captures the control
flow of each input file(s), by using another two libraries:

-[cdmcfparser](https://pypi.org/project/cdmcfparser/): The module provided functions can takes a file with a python code or a character buffer, parse it and provide back a hierarchical representation of the code in terms of fragments. Each fragment describes a portion of the input: a start point (line, column and absolute position) plus an end point (line, column and absolute position).

-[staticfg](./staticfg): StatiCFG is a package that can be used to produce control flow graphs (CFGs) for Python 3 programs. The CFGs it generates can be easily visualised with graphviz and used for static analysis. We have a flag in the code (FLAG_PNG) to indicate if we want to generate this type of control flow graphs or not. 

!!! info
    The original code of this package can be found [here](https://github.com/coetaur0/staticfg), but given a bug in the package's source code, we forked it, and fixed it in our [repository](./staticfg)  

For parsing the docstrings, we use [docstring_parser](https://pypi.org/project/docstring-parser/), which has support for  ReST, Google, and Numpydoc-style docstrings. Some (basic) tests done using this library can be found at [here](./test_docstring_parser/).

It also usese [Pigar](https://github.com/damnever/pigar) for generating automatically the requirements of a given repository. This is an optional funcionality. In order to activate the argument (-r) has to be indicated when we run the code_inspector.  

## Install

### Installation from code

First, make sure you have graphviz installed:

```
sudo apt-get install graphviz
```

Then, prepare a virtual Python3 enviroment and install the required packages.

`pip install -r requirements.txt`

- Dependencies: 
  - cdmcfparser==2.3.2
  - docstring_parser==0.7
  - astor
  - graphviz
  - Click
  - setuptools == 54.2.0
  - json2html

### Installation through Docker

First, you will need to have [Docker](https://docs.docker.com/get-started/) installed.

Next, clone this repository:

```
git clone https://github.com/rosafilgueira/code_inspector/
```

Generate a Docker image for code_inspector:

```
docker build --tag inspector:1.0 .
```

Run code_inspector (you will have to copy the target data inside the image for analysis):

```
docker run -it --rm --entrypoint "/bin/bash" inspector:1.0
```

And then run `code_inspector` following the commands outlined in the sections below


Other useful commands when using Docker:
```
docker cp [OPTIONS] CONTAINER:SRC_PATH DEST_PATH|-
docker run -it --entrypoint "/bin/bash" inspector:1.0
docker image rm -f inspector:1.0
```