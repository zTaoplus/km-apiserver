# Kernel Manager API Server

## Overview

The Kernel Manager API Server is a server that provides a REST API for the Kernel Manager in k8s and also provides a websocket connection for the kernel.

Inspired by [Jupyter Server](https://github.com/jupyter-server/jupyter_server), [Enterprise Gateway](https://github.com/jupyter-server/enterprise_gateway)

## Requirements

- Python 3.10+
- Kubernetes(KM CRDs installed to cluster)

## Installation

### Install uv

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

more details: [uv-installation](https://docs.astral.sh/uv/getting-started/installation/)

### Install dependencies

```sh
# cd <project> 
uv sync 
```

## Usage

### Environment Variables

| Environment Variable | Description | Default Value |
|---------------------|-------------|---------------|
| LOG_LEVEL | Logging level | INFO |
| ALLOW_UNAUTHENTICATED_ACCESS | Allow unauthenticated access | false |
| USER_IN_HEADER | Header containing the user identity (used for authentication and ignored if ALLOW_UNAUTHENTICATED_ACCESS is true) | X-Forwarded-User |

### Run

```sh
uv run python -m km_apiserver --port 8888 # default port is 8888
```

## OpenAPI

Visit <http://localhost:8888/api/docs> in your browser to view the OpenAPI specification

## Test

### install test dependencies

```sh
uv sync --extra test
```

### run tests

```sh
uv run pytest tests
```
