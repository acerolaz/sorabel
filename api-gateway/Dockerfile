FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /source

COPY Sorabel.ApiGateway.sln ./
COPY src/ ./src/
RUN dotnet publish src/Sorabel.ApiGateway.Api -c Release -o /app --no-self-contained

FROM mcr.microsoft.com/dotnet/aspnet:9.0 AS runtime
WORKDIR /app

# Utilisateur non-root fourni par l'image de base.
USER $APP_UID

COPY --from=build /app ./

ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["dotnet", "Sorabel.ApiGateway.Api.dll", "--healthcheck"]

ENTRYPOINT ["dotnet", "Sorabel.ApiGateway.Api.dll"]
