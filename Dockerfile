# Share server for claude-logbook (see server/README.md).
# Built from the repo root: it embeds claude_logbook/template.html.
FROM golang:1.23-alpine AS build
WORKDIR /src
COPY server/ ./
COPY claude_logbook/template.html ./template.html
RUN CGO_ENABLED=0 go test ./... \
 && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/server . \
 && mkdir -p /out/data

FROM scratch
COPY --from=build /out/server /server
COPY --from=build --chown=65534:65534 /out/data /data
USER 65534:65534
EXPOSE 8181
VOLUME /data
HEALTHCHECK --interval=30s --timeout=5s CMD ["/server", "-healthcheck"]
ENTRYPOINT ["/server"]
