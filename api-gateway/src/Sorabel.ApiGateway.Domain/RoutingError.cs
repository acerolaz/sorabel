namespace Sorabel.ApiGateway.Domain;

public enum RoutingErrorKind
{
    BackendUnreachable,
    BackendTimeout,
}

/// <summary>
/// Les deux seules erreurs que la gateway fabrique elle-même. Toute réponse
/// effectivement reçue d'un backend — y compris 403 ou 500 — est relayée
/// verbatim et ne passe jamais par ici.
/// </summary>
public sealed record RoutingError(RoutingErrorKind Kind)
{
    public int StatusCode => Kind switch
    {
        RoutingErrorKind.BackendTimeout => 504,
        _ => 502,
    };

    public string ErrorCode => Kind switch
    {
        RoutingErrorKind.BackendTimeout => "BACKEND_TIMEOUT",
        _ => "BACKEND_UNREACHABLE",
    };

    // Volontairement identique pour les deux cas et dépourvu de toute
    // information de topologie : le code métier porte la distinction.
    public string Message => "Le service demandé est momentanément indisponible";
}
