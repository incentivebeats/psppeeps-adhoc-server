FROM alpine:3.23 AS build

WORKDIR /app
RUN apk add --no-cache \
  g++ \
  make \
  sqlite-dev

COPY . .
RUN make

FROM alpine:3.23

WORKDIR /app
RUN apk add --no-cache \
  sqlite-libs

COPY --from=build /app/AdhocServer /app/AdhocServer
COPY --from=build /app/database.db /app/database.db

EXPOSE 27312/tcp
ENTRYPOINT [ "/app/AdhocServer" ]
