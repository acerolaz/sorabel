using System.Text.Json.Serialization;

namespace Sorabel.ApiGateway.Infrastructure.Errors;

/// <summary>
/// Contrat d'erreur commun à toutes les API de la solution
/// (.claude/rules/api-contracts.md) : champs en snake_case, code métier stable.
/// </summary>
public sealed record GatewayErrorResponse(
    [property: JsonPropertyName("error_code")] string ErrorCode,
    [property: JsonPropertyName("message")] string Message,
    [property: JsonPropertyName("correlation_id")] string CorrelationId);
