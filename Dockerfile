FROM ghcr.io/astral-sh/uv:0.5.13 as uv


FROM python:3.12-slim as python


COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app


COPY uv.lock pyproject.toml .
RUN uv sync --no-cache  && rm uv.lock pyproject.toml -f 


# We have set tool.uv.package=false in pyproject.toml to avoid installing the project package, 
# allowing the source code layer to be copied after dependency installation. This approach also better utilizes Docker's cache layers and 
# speeds up the build process since changes in the code do not invalidate the dependency layer.
COPY mkm ./mkm

# Because mkm not installed, we need to run it using `python -m`
CMD ["uv", "run", "python", "-m", "mkm"]
