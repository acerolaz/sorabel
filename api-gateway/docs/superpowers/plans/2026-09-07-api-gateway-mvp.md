# api-gateway MVP — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le hub de routage pur de la solution Sorabel : un reverse-proxy YARP qui relaie clients et appels internes vers cinq backends, sans jamais lire un JWT ni prendre de décision d'autorisation.

**Architecture:** YARP porte 100 % du forwarding via configuration déclarative. Trois projets — `Domain` (sans dépendance), `Infrastructure` (résilience, corrélation, erreurs), `Api` (host ASP.NET). Pas de couche Application ni de MediatR : aucun cas d'usage métier à orchestrer.

**Tech Stack:** .NET 9 (`9.0.202` vérifié sur le poste), `Yarp.ReverseProxy` 2.3.0, xUnit, WireMock.Net, Docker.

**Spec:** `docs/superpowers/specs/2026-09-07-api-gateway-design.md` (dans ce même projet)

## Global Constraints

Ces contraintes s'appliquent à **toutes** les tâches. Toute tâche qui les viole doit être rejetée en revue.

- **Aucune logique d'autorisation.** Aucun code ne lit, décode ou interprète un claim JWT, un rôle ou une matrice RBAC. L'en-tête `Authorization` est relayé octet pour octet et n'est jamais inspecté.
- **`Sorabel.ApiGateway.Domain` ne référence aucun paquet NuGet.** Le framework partagé .NET est autorisé, rien d'autre. Pas d'ASP.NET, pas de YARP.
- **Toute réponse reçue d'un backend est relayée verbatim** — statut, corps et en-têtes inchangés, y compris 403 et 500. La gateway ne fabrique une réponse que lorsqu'il n'y a **aucune** réponse.
- **Une requête cliente = au plus une exécution backend.** Aucun rejeu sur timeout, aucun rejeu sur réponse reçue, aucun rejeu d'une requête portant un corps.
- **Aucun secret en dur**, y compris dans les tests. Les adresses de backends viennent de la configuration.
- **Jamais d'`Authorization` ni de corps de requête/réponse dans les logs.**
- **Cible .NET : `net9.0`.** Version du paquet YARP : `2.3.0`.
- **Messages de commit** : Conventional Commits, scope `api-gateway`, en français, **sans aucune métadonnée d'IA** (cf. `.claude/rules/git-conventions.md`).
- **Ne jamais committer sur `main`.** Travailler sur une branche `feat/api-gateway/<description>`.
- **Niveaux de test** : conformes à la spec (design §8). Les tests de niveau 4 portent `[Trait("Category", "E2E")]` et sont exclus de `make test`.

## Décision technique découverte pendant la préparation du plan

**Le retry ne s'applique jamais à une requête portant un corps.** YARP transmet le corps de la requête entrante en streaming, via un contenu HTTP à usage unique. Rejouer une telle requête enverrait un corps vide au second essai — une corruption silencieuse bien pire que l'échec qu'on cherchait à absorber.

Conséquence : le retry couvre en pratique les `GET` sans corps, dont la récupération JWKS sur `/internal/v1/auth`. Tous les `call_tool` en `POST` échouent immédiatement en 502. C'est un renforcement de la garantie « au plus une exécution », pas un affaiblissement. Cette contrainte est encodée dans `RetryDecision` (Tâche 2) et vérifiée par un test dédié.

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `Sorabel.ApiGateway.sln` | Solution : 3 projets sources + 3 projets de tests |
| `src/Sorabel.ApiGateway.Domain/BackendId.cs` | Identifiant de backend, liste fermée |
| `src/Sorabel.ApiGateway.Domain/CorrelationId.cs` | Génération, parsing, validation du correlation ID |
| `src/Sorabel.ApiGateway.Domain/RoutingError.cs` | Les deux erreurs fabriquées par la gateway + leur code HTTP et métier |
| `src/Sorabel.ApiGateway.Domain/RetryDecision.cs` | « Cet échec est-il rejouable ? » — la décision la plus sensible du projet |
| `src/Sorabel.ApiGateway.Domain/SensitiveHeaders.cs` | Liste des en-têtes qui ne doivent jamais être journalisés |
| `src/Sorabel.ApiGateway.Infrastructure/Resilience/RetryHandler.cs` | `DelegatingHandler` appliquant `RetryDecision` |
| `src/Sorabel.ApiGateway.Infrastructure/Resilience/ResilientForwarderHttpClientFactory.cs` | Point de greffe du handler dans YARP |
| `src/Sorabel.ApiGateway.Infrastructure/Correlation/CorrelationMiddleware.cs` | Lecture/génération, scope de log, en-tête de réponse |
| `src/Sorabel.ApiGateway.Infrastructure/Correlation/CorrelationTransform.cs` | Injection de l'en-tête dans la requête sortante |
| `src/Sorabel.ApiGateway.Infrastructure/Errors/ForwarderErrorTranslator.cs` | `ForwarderError` (YARP) → `RoutingError` (Domain) |
| `src/Sorabel.ApiGateway.Infrastructure/Errors/ForwarderErrorMiddleware.cs` | Écrit la réponse d'erreur JSON |
| `src/Sorabel.ApiGateway.Infrastructure/Errors/GatewayErrorResponse.cs` | DTO du contrat d'erreur, en `snake_case` |
| `src/Sorabel.ApiGateway.Infrastructure/Logging/RequestLoggingMiddleware.cs` | Une ligne structurée par requête relayée |
| `src/Sorabel.ApiGateway.Api/Program.cs` | Composition : services, pipeline, `MapReverseProxy` |
| `src/Sorabel.ApiGateway.Api/appsettings.Routes.json` | **Le contrat de routage** — 6 routes, 5 clusters |
| `Dockerfile`, `docker-compose.yml`, `.env.example` | Packaging |

---

## Tâche 1 : Squelette de solution et `RetryDecision`

Fonde la solution et livre la première brique de domaine — celle qui porte la garantie « au plus une exécution ».

**Files:**
- Create: `Sorabel.ApiGateway.sln`
- Create: `src/Sorabel.ApiGateway.Domain/Sorabel.ApiGateway.Domain.csproj`
- Create: `src/Sorabel.ApiGateway.Domain/RetryDecision.cs`
- Create: `tests/Sorabel.ApiGateway.Domain.Tests/Sorabel.ApiGateway.Domain.Tests.csproj`
- Create: `tests/Sorabel.ApiGateway.Domain.Tests/RetryDecisionTests.cs`
- Modify: `Makefile`

**Interfaces:**
- Consumes: rien (première tâche)
- Produces: `Sorabel.ApiGateway.Domain.RetryDecision.CanRetry(HttpRequestError error, bool requestHasBody) -> bool`

- [ ] **Étape 1 : Créer la branche et le squelette de solution**

```bash
cd api-gateway
git checkout -b feat/api-gateway/mvp

dotnet new sln -n Sorabel.ApiGateway
dotnet new classlib -n Sorabel.ApiGateway.Domain -o src/Sorabel.ApiGateway.Domain -f net9.0
dotnet new xunit  -n Sorabel.ApiGateway.Domain.Tests -o tests/Sorabel.ApiGateway.Domain.Tests -f net9.0

rm src/Sorabel.ApiGateway.Domain/Class1.cs
rm tests/Sorabel.ApiGateway.Domain.Tests/UnitTest1.cs

dotnet sln add src/Sorabel.ApiGateway.Domain tests/Sorabel.ApiGateway.Domain.Tests
dotnet add tests/Sorabel.ApiGateway.Domain.Tests reference src/Sorabel.ApiGateway.Domain
```

- [ ] **Étape 2 : Activer le nullable et les warnings-as-errors sur les deux projets**

Dans `src/Sorabel.ApiGateway.Domain/Sorabel.ApiGateway.Domain.csproj`, à l'intérieur du `<PropertyGroup>` existant :

```xml
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
```

Faire la même chose dans `tests/Sorabel.ApiGateway.Domain.Tests/Sorabel.ApiGateway.Domain.Tests.csproj`.

- [ ] **Étape 3 : Écrire le test qui échoue**

Créer `tests/Sorabel.ApiGateway.Domain.Tests/RetryDecisionTests.cs` :

```csharp
using System.Net.Http;
using Sorabel.ApiGateway.Domain;
using Xunit;

namespace Sorabel.ApiGateway.Domain.Tests;

public class RetryDecisionTests
{
    // Rejouable : le backend n'a certainement rien reçu, et il n'y a pas de corps
    // à retransmettre.
    [Theory]
    [InlineData(HttpRequestError.ConnectionError)]
    [InlineData(HttpRequestError.NameResolutionError)]
    public void Rejoue_les_echecs_de_connexion_sans_corps(HttpRequestError error)
    {
        Assert.True(RetryDecision.CanRetry(error, requestHasBody: false));
    }

    // Non rejouable : YARP transmet le corps en streaming via un contenu à usage
    // unique. Un second essai enverrait un corps vide — corruption silencieuse.
    [Theory]
    [InlineData(HttpRequestError.ConnectionError)]
    [InlineData(HttpRequestError.NameResolutionError)]
    public void Ne_rejoue_jamais_une_requete_portant_un_corps(HttpRequestError error)
    {
        Assert.False(RetryDecision.CanRetry(error, requestHasBody: true));
    }

    // Non rejouable : dans tous ces cas la requête a pu être reçue et traitée.
    // Rejouer produirait une double exécution SQL et une double entrée d'audit.
    [Theory]
    [InlineData(HttpRequestError.Unknown)]
    [InlineData(HttpRequestError.SecureConnectionError)]
    [InlineData(HttpRequestError.HttpProtocolError)]
    [InlineData(HttpRequestError.ResponseEnded)]
    [InlineData(HttpRequestError.InvalidResponse)]
    [InlineData(HttpRequestError.ConfigurationLimitExceeded)]
    [InlineData(HttpRequestError.VersionNegotiationError)]
    [InlineData(HttpRequestError.UserAuthenticationError)]
    [InlineData(HttpRequestError.ProxyTunnelError)]
    [InlineData(HttpRequestError.ExtendedConnectNotSupported)]
    public void Ne_rejoue_aucun_autre_type_d_echec(HttpRequestError error)
    {
        Assert.False(RetryDecision.CanRetry(error, requestHasBody: false));
        Assert.False(RetryDecision.CanRetry(error, requestHasBody: true));
    }
}
```

- [ ] **Étape 4 : Lancer le test et vérifier qu'il échoue**

```bash
dotnet test tests/Sorabel.ApiGateway.Domain.Tests
```

Attendu : ÉCHEC de compilation — `RetryDecision` n'existe pas.

- [ ] **Étape 5 : Écrire l'implémentation minimale**

Créer `src/Sorabel.ApiGateway.Domain/RetryDecision.cs` :

```csharp
using System.Net.Http;

namespace Sorabel.ApiGateway.Domain;

/// <summary>
/// Décide si un échec de transfert vers un backend peut être rejoué.
///
/// Le catalogue MCP n'expose que des appels POST, dont certains ont des effets
/// audités (run_sql_query s'exécute et se journalise) ou facturés (ask_database
/// déclenche une génération LLM). Un rejeu produirait une seconde exécution et
/// une seconde entrée d'audit, rendant E5 trompeur.
///
/// Le rejeu est donc restreint aux cas où l'on a la CERTITUDE que le backend
/// n'a rien reçu, et où la requête ne porte pas de corps : YARP transmet le
/// corps entrant en streaming via un contenu à usage unique, qu'un second essai
/// enverrait vide.
/// </summary>
public static class RetryDecision
{
    public static bool CanRetry(HttpRequestError error, bool requestHasBody)
    {
        if (requestHasBody)
        {
            return false;
        }

        return error is HttpRequestError.ConnectionError
                     or HttpRequestError.NameResolutionError;
    }
}
```

- [ ] **Étape 6 : Lancer le test et vérifier qu'il passe**

```bash
dotnet test tests/Sorabel.ApiGateway.Domain.Tests
```

Attendu : SUCCÈS, 24 tests passés.

- [ ] **Étape 7 : Mettre le Makefile en conformité avec la règle de pyramide de tests**

Remplacer les cibles `test` et ajouter `test-e2e` dans `Makefile` :

```makefile
.PHONY: build test test-e2e lint docker-build docker-up docker-down clean

test:
	dotnet test --filter "Category!=E2E"

test-e2e:
	dotnet test --filter "Category=E2E"
```

Conserver les autres cibles telles quelles.

- [ ] **Étape 8 : Vérifier l'ensemble**

```bash
make build && make test && make lint
```

Attendu : les trois passent. Si `make lint` échoue, lancer `dotnet format` puis relancer.

- [ ] **Étape 9 : Committer**

```bash
git add Sorabel.ApiGateway.sln src tests Makefile
git commit -m "feat(api-gateway): initialise la solution et la règle de rejeu

RetryDecision restreint le rejeu aux échecs de connexion sans corps de
requête : YARP transmet le corps en streaming via un contenu à usage
unique, qu'un second essai enverrait vide. Garantit qu'une requête
cliente ne provoque jamais plus d'une exécution backend."
```

---

## Tâche 2 : Le reste du domaine — `CorrelationId`, `BackendId`, `RoutingError`, `SensitiveHeaders`

**Files:**
- Create: `src/Sorabel.ApiGateway.Domain/CorrelationId.cs`
- Create: `src/Sorabel.ApiGateway.Domain/BackendId.cs`
- Create: `src/Sorabel.ApiGateway.Domain/RoutingError.cs`
- Create: `src/Sorabel.ApiGateway.Domain/SensitiveHeaders.cs`
- Create: `tests/Sorabel.ApiGateway.Domain.Tests/CorrelationIdTests.cs`
- Create: `tests/Sorabel.ApiGateway.Domain.Tests/RoutingErrorTests.cs`

**Interfaces:**
- Consumes: rien de la Tâche 1
- Produces :
  - `CorrelationId.HeaderName -> const string` (`"X-Correlation-Id"`)
  - `CorrelationId.New() -> CorrelationId`
  - `CorrelationId.FromHeaderOrNew(string? header) -> CorrelationId`
  - `CorrelationId.TryParse(string? candidate, out CorrelationId id) -> bool`
  - `CorrelationId.Value -> string`
  - `BackendId.Idp | Mcp | Text2Sql | Sql | Rag`, `BackendId.Value -> string`, `BackendId.TryFromClusterId(string?, out BackendId) -> bool`
  - `RoutingErrorKind.BackendUnreachable | BackendTimeout`
  - `RoutingError.Kind`, `.StatusCode -> int`, `.ErrorCode -> string`, `.Message -> string`
  - `SensitiveHeaders.Names -> IReadOnlySet<string>`

- [ ] **Étape 1 : Écrire les tests de `CorrelationId`**

Créer `tests/Sorabel.ApiGateway.Domain.Tests/CorrelationIdTests.cs` :

```csharp
using Sorabel.ApiGateway.Domain;
using Xunit;

namespace Sorabel.ApiGateway.Domain.Tests;

public class CorrelationIdTests
{
    [Fact]
    public void New_genere_un_identifiant_non_vide_et_unique()
    {
        var a = CorrelationId.New();
        var b = CorrelationId.New();

        Assert.False(string.IsNullOrWhiteSpace(a.Value));
        Assert.NotEqual(a.Value, b.Value);
    }

    [Fact]
    public void Reprend_un_identifiant_entrant_valide()
    {
        var id = CorrelationId.FromHeaderOrNew("7f3a91e4-1234-4abc-9def-000000000001");

        Assert.Equal("7f3a91e4-1234-4abc-9def-000000000001", id.Value);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void Genere_un_identifiant_quand_l_entete_est_absent(string? header)
    {
        var id = CorrelationId.FromHeaderOrNew(header);

        Assert.False(string.IsNullOrWhiteSpace(id.Value));
    }

    // L'en-tête est contrôlé par l'appelant et finit dans les logs : un retour
    // chariot permettrait d'y injecter une fausse ligne. Une valeur non conforme
    // est remplacée, jamais assainie puis conservée.
    [Theory]
    [InlineData("abc\r\nFAUSSE-LIGNE: injection")]
    [InlineData("abc\ndef")]
    [InlineData("valeur avec espaces")]
    [InlineData("point.virgule;")]
    [InlineData("<script>")]
    public void Remplace_une_valeur_entrante_non_conforme(string header)
    {
        var id = CorrelationId.FromHeaderOrNew(header);

        Assert.NotEqual(header, id.Value);
        Assert.DoesNotContain('\r', id.Value);
        Assert.DoesNotContain('\n', id.Value);
    }

    [Fact]
    public void Remplace_une_valeur_entrante_trop_longue()
    {
        var trop_long = new string('a', 129);

        var id = CorrelationId.FromHeaderOrNew(trop_long);

        Assert.NotEqual(trop_long, id.Value);
    }
}
```

- [ ] **Étape 2 : Écrire les tests de `RoutingError`**

Créer `tests/Sorabel.ApiGateway.Domain.Tests/RoutingErrorTests.cs` :

```csharp
using Sorabel.ApiGateway.Domain;
using Xunit;

namespace Sorabel.ApiGateway.Domain.Tests;

public class RoutingErrorTests
{
    [Fact]
    public void Backend_injoignable_est_un_502_avec_un_code_metier_stable()
    {
        var error = new RoutingError(RoutingErrorKind.BackendUnreachable);

        Assert.Equal(502, error.StatusCode);
        Assert.Equal("BACKEND_UNREACHABLE", error.ErrorCode);
    }

    [Fact]
    public void Timeout_backend_est_un_504_avec_un_code_metier_stable()
    {
        var error = new RoutingError(RoutingErrorKind.BackendTimeout);

        Assert.Equal(504, error.StatusCode);
        Assert.Equal("BACKEND_TIMEOUT", error.ErrorCode);
    }

    // Le message d'erreur ne doit pas cartographier la topologie interne :
    // ni nom de backend, ni nom d'hôte, ni port.
    [Theory]
    [InlineData(RoutingErrorKind.BackendUnreachable)]
    [InlineData(RoutingErrorKind.BackendTimeout)]
    public void Le_message_ne_nomme_aucun_backend(RoutingErrorKind kind)
    {
        var message = new RoutingError(kind).Message;

        foreach (var interdit in new[] { "mcp", "text2sql", "keycloak", "sorabelsql", "rag", "http", ":8" })
        {
            Assert.DoesNotContain(interdit, message, StringComparison.OrdinalIgnoreCase);
        }
    }
}
```

- [ ] **Étape 3 : Lancer les tests et vérifier qu'ils échouent**

```bash
dotnet test tests/Sorabel.ApiGateway.Domain.Tests
```

Attendu : ÉCHEC de compilation — `CorrelationId` et `RoutingError` n'existent pas.

- [ ] **Étape 4 : Implémenter `CorrelationId`**

Créer `src/Sorabel.ApiGateway.Domain/CorrelationId.cs` :

```csharp
namespace Sorabel.ApiGateway.Domain;

/// <summary>
/// Identifiant de corrélation propagé de bout en bout par l'en-tête
/// X-Correlation-Id. Une valeur entrante non conforme est remplacée : elle
/// finit dans les logs, où un retour chariot permettrait d'injecter une
/// fausse ligne.
/// </summary>
public readonly record struct CorrelationId
{
    public const string HeaderName = "X-Correlation-Id";

    private const int MaxLength = 128;

    private CorrelationId(string value) => Value = value;

    public string Value { get; }

    public static CorrelationId New() => new(Guid.NewGuid().ToString("D"));

    public static CorrelationId FromHeaderOrNew(string? header)
        => TryParse(header, out var id) ? id : New();

    public static bool TryParse(string? candidate, out CorrelationId id)
    {
        id = default;

        if (string.IsNullOrWhiteSpace(candidate) || candidate.Length > MaxLength)
        {
            return false;
        }

        foreach (var c in candidate)
        {
            if (!char.IsAsciiLetterOrDigit(c) && c is not ('-' or '_'))
            {
                return false;
            }
        }

        id = new CorrelationId(candidate);
        return true;
    }

    public override string ToString() => Value;
}
```

- [ ] **Étape 5 : Implémenter `RoutingError`**

Créer `src/Sorabel.ApiGateway.Domain/RoutingError.cs` :

```csharp
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
```

- [ ] **Étape 6 : Implémenter `BackendId` et `SensitiveHeaders`**

Créer `src/Sorabel.ApiGateway.Domain/BackendId.cs` :

```csharp
namespace Sorabel.ApiGateway.Domain;

/// <summary>
/// Liste fermée des backends de la solution. La valeur correspond exactement
/// au ClusterId déclaré dans appsettings.Routes.json.
/// </summary>
public readonly record struct BackendId
{
    public static readonly BackendId Idp = new("idp");
    public static readonly BackendId Mcp = new("mcp");
    public static readonly BackendId Text2Sql = new("text2sql");
    public static readonly BackendId Sql = new("sql");
    public static readonly BackendId Rag = new("rag");

    private BackendId(string value) => Value = value;

    public string Value { get; }

    public static IReadOnlyList<BackendId> All => [Idp, Mcp, Text2Sql, Sql, Rag];

    public static bool TryFromClusterId(string? clusterId, out BackendId id)
    {
        foreach (var candidate in All)
        {
            if (string.Equals(candidate.Value, clusterId, StringComparison.Ordinal))
            {
                id = candidate;
                return true;
            }
        }

        id = default;
        return false;
    }

    public override string ToString() => Value;
}
```

Créer `src/Sorabel.ApiGateway.Domain/SensitiveHeaders.cs` :

```csharp
namespace Sorabel.ApiGateway.Domain;

/// <summary>
/// En-têtes qui ne doivent jamais apparaître dans un log, sous aucune forme.
/// La gateway relaie le JWT sans le lire ; elle ne doit pas non plus le laisser
/// fuiter par la journalisation.
/// </summary>
public static class SensitiveHeaders
{
    public static IReadOnlySet<string> Names { get; } =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "Authorization",
            "Proxy-Authorization",
            "Cookie",
            "Set-Cookie",
        };

    public static bool IsSensitive(string headerName) => Names.Contains(headerName);
}
```

- [ ] **Étape 7 : Lancer les tests et vérifier qu'ils passent**

```bash
make test
```

Attendu : SUCCÈS, tous les tests du projet Domain passent.

- [ ] **Étape 8 : Committer**

```bash
git add src/Sorabel.ApiGateway.Domain tests/Sorabel.ApiGateway.Domain.Tests
git commit -m "feat(api-gateway): ajoute les value objects du domaine

CorrelationId remplace toute valeur entrante non conforme plutôt que de
l'assainir : l'en-tête est contrôlé par l'appelant et finit dans les logs.
RoutingError ne couvre que les deux erreurs fabriquées par la gateway ;
son message ne nomme aucun backend, pour ne pas cartographier la
topologie interne via la réponse d'erreur."
```

---

## Tâche 3 : Host ASP.NET, YARP et le contrat de routage

Livre les 6 routes de la spec et prouve qu'elles atteignent le bon backend.

**Files:**
- Create: `src/Sorabel.ApiGateway.Api/Sorabel.ApiGateway.Api.csproj`
- Create: `src/Sorabel.ApiGateway.Api/Program.cs`
- Create: `src/Sorabel.ApiGateway.Api/appsettings.json`
- Create: `src/Sorabel.ApiGateway.Api/appsettings.Routes.json`
- Create: `tests/Sorabel.ApiGateway.Api.Tests/Sorabel.ApiGateway.Api.Tests.csproj`
- Create: `tests/Sorabel.ApiGateway.Api.Tests/GatewayFixture.cs`
- Create: `tests/Sorabel.ApiGateway.Api.Tests/RoutingContractTests.cs`

**Interfaces:**
- Consumes: rien du domaine pour l'instant
- Produces :
  - `public partial class Program` (rendu visible pour `WebApplicationFactory`)
  - `GatewayFixture.CreateClient(IReadOnlyDictionary<string, string> destinations) -> HttpClient`
  - Cluster IDs : `idp`, `mcp`, `text2sql`, `sql`, `rag`

- [ ] **Étape 1 : Créer les projets Api et Api.Tests**

```bash
dotnet new web   -n Sorabel.ApiGateway.Api -o src/Sorabel.ApiGateway.Api -f net9.0
dotnet new xunit -n Sorabel.ApiGateway.Api.Tests -o tests/Sorabel.ApiGateway.Api.Tests -f net9.0
rm tests/Sorabel.ApiGateway.Api.Tests/UnitTest1.cs

dotnet sln add src/Sorabel.ApiGateway.Api tests/Sorabel.ApiGateway.Api.Tests

dotnet add src/Sorabel.ApiGateway.Api package Yarp.ReverseProxy --version 2.3.0
dotnet add src/Sorabel.ApiGateway.Api reference src/Sorabel.ApiGateway.Domain

dotnet add tests/Sorabel.ApiGateway.Api.Tests package Microsoft.AspNetCore.Mvc.Testing
dotnet add tests/Sorabel.ApiGateway.Api.Tests package WireMock.Net
dotnet add tests/Sorabel.ApiGateway.Api.Tests reference src/Sorabel.ApiGateway.Api
```

Ajouter `<Nullable>enable</Nullable>`, `<ImplicitUsings>enable</ImplicitUsings>` et `<TreatWarningsAsErrors>true</TreatWarningsAsErrors>` aux deux `.csproj`, comme en Tâche 1.

- [ ] **Étape 2 : Écrire le harnais de test**

Créer `tests/Sorabel.ApiGateway.Api.Tests/GatewayFixture.cs` :

```csharp
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using WireMock.Server;

namespace Sorabel.ApiGateway.Api.Tests;

/// <summary>
/// Démarre la gateway en mémoire, avec des backends WireMock à la place des
/// vraies destinations. Les adresses sont surchargées par configuration,
/// exactement comme elles le seront en production.
/// </summary>
public sealed class GatewayFixture : IDisposable
{
    private readonly List<WireMockServer> _servers = [];
    private readonly List<WebApplicationFactory<Program>> _factories = [];

    public WireMockServer StartBackend()
    {
        var server = WireMockServer.Start();
        _servers.Add(server);
        return server;
    }

    /// <param name="destinations">clusterId → adresse de base du backend.</param>
    public HttpClient CreateClient(IReadOnlyDictionary<string, string> destinations)
    {
        var overrides = destinations.ToDictionary(
            kv => $"ReverseProxy:Clusters:{kv.Key}:Destinations:d1:Address",
            kv => (string?)kv.Value);

        var factory = new WebApplicationFactory<Program>()
            .WithWebHostBuilder(builder => builder.ConfigureAppConfiguration(
                (_, config) => config.AddInMemoryCollection(overrides)));

        _factories.Add(factory);
        return factory.CreateClient();
    }

    public void Dispose()
    {
        foreach (var factory in _factories) factory.Dispose();
        foreach (var server in _servers) server.Stop();
    }
}
```

- [ ] **Étape 3 : Écrire les tests de contrat de routage**

Créer `tests/Sorabel.ApiGateway.Api.Tests/RoutingContractTests.cs` :

```csharp
using System.Net;
using System.Net.Http.Headers;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using Xunit;

namespace Sorabel.ApiGateway.Api.Tests;

[Trait("Level", "3")]
public class RoutingContractTests : IClassFixture<GatewayFixture>
{
    private readonly GatewayFixture _fixture;

    public RoutingContractTests(GatewayFixture fixture) => _fixture = fixture;

    // Les 6 routes du contrat, avec le cluster qu'elles doivent atteindre et le
    // chemin que le backend doit recevoir une fois le préfixe retiré.
    public static TheoryData<string, string, string> Routes => new()
    {
        { "idp",      "/api/v1/auth/realms/sorabel-data-gate/token", "/realms/sorabel-data-gate/token" },
        { "mcp",      "/api/v1/mcp/call_tool",                       "/call_tool" },
        { "idp",      "/internal/v1/auth/realms/x/certs",            "/realms/x/certs" },
        { "text2sql", "/internal/v1/text2sql/generate",              "/generate" },
        { "sql",      "/internal/v1/sql/run",                        "/run" },
        { "rag",      "/internal/v1/rag/search",                     "/search" },
    };

    [Theory]
    [MemberData(nameof(Routes))]
    public async Task Atteint_le_bon_backend_avec_le_prefixe_retire(
        string clusterId, string cheminEntrant, string cheminAttendu)
    {
        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath(cheminAttendu))
            .RespondWith(Response.Create().WithStatusCode(200).WithBody("ok"));

        var client = _fixture.CreateClient(new Dictionary<string, string>
        {
            [clusterId] = backend.Url!,
        });

        var response = await client.GetAsync(cheminEntrant);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("ok", await response.Content.ReadAsStringAsync());

        var recue = Assert.Single(backend.LogEntries);
        Assert.Equal(cheminAttendu, recue.RequestMessage.Path);
    }

    // Non-négociable : le JWT traverse la gateway sans être lu ni modifié.
    [Fact]
    public async Task Relaie_l_entete_Authorization_octet_pour_octet()
    {
        const string jeton = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.charge-utile.signature";

        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath("/call_tool"))
            .RespondWith(Response.Create().WithStatusCode(200));

        var client = _fixture.CreateClient(new Dictionary<string, string> { ["mcp"] = backend.Url! });
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", jeton);

        await client.GetAsync("/api/v1/mcp/call_tool");

        var recue = Assert.Single(backend.LogEntries);
        Assert.Equal($"Bearer {jeton}", recue.RequestMessage.Headers!["Authorization"].Single());
    }

    [Fact]
    public async Task Health_repond_sans_toucher_a_un_backend()
    {
        var client = _fixture.CreateClient(new Dictionary<string, string>());

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }
}
```

- [ ] **Étape 4 : Lancer les tests et vérifier qu'ils échouent**

```bash
dotnet test tests/Sorabel.ApiGateway.Api.Tests
```

Attendu : ÉCHEC — aucune route n'est déclarée, les requêtes retournent 404.

- [ ] **Étape 5 : Écrire le contrat de routage**

Créer `src/Sorabel.ApiGateway.Api/appsettings.Routes.json`.

Note sur les timeouts : le timeout d'une route externe doit **dépasser** celui de la route interne la plus lente qu'elle peut déclencher. Un `call_tool("ask_database")` traverse la gateway deux fois — `/api/v1/mcp` (120 s) englobe `/internal/v1/text2sql` (90 s).

```json
{
  "ReverseProxy": {
    "Routes": {
      "auth-public": {
        "ClusterId": "idp",
        "Match": { "Path": "/api/v1/auth/{**rest}" },
        "Timeout": "00:00:10",
        "Transforms": [ { "PathRemovePrefix": "/api/v1/auth" } ]
      },
      "mcp-public": {
        "ClusterId": "mcp",
        "Match": { "Path": "/api/v1/mcp/{**rest}" },
        "Timeout": "00:02:00",
        "Transforms": [ { "PathRemovePrefix": "/api/v1/mcp" } ]
      },
      "auth-internal": {
        "ClusterId": "idp",
        "Match": { "Path": "/internal/v1/auth/{**rest}" },
        "Timeout": "00:00:10",
        "Transforms": [ { "PathRemovePrefix": "/internal/v1/auth" } ]
      },
      "text2sql-internal": {
        "ClusterId": "text2sql",
        "Match": { "Path": "/internal/v1/text2sql/{**rest}" },
        "Timeout": "00:01:30",
        "Transforms": [ { "PathRemovePrefix": "/internal/v1/text2sql" } ]
      },
      "sql-internal": {
        "ClusterId": "sql",
        "Match": { "Path": "/internal/v1/sql/{**rest}" },
        "Timeout": "00:00:30",
        "Transforms": [ { "PathRemovePrefix": "/internal/v1/sql" } ]
      },
      "rag-internal": {
        "ClusterId": "rag",
        "Match": { "Path": "/internal/v1/rag/{**rest}" },
        "Timeout": "00:00:30",
        "Transforms": [ { "PathRemovePrefix": "/internal/v1/rag" } ]
      }
    },
    "Clusters": {
      "idp":      { "Destinations": { "d1": { "Address": "http://sorabel-idp:8080/" } } },
      "mcp":      { "Destinations": { "d1": { "Address": "http://mcp:8000/" } } },
      "text2sql": { "Destinations": { "d1": { "Address": "http://text2sql-ai:8000/" } } },
      "sql":      { "Destinations": { "d1": { "Address": "http://sorabelsql-api:8080/" } } },
      "rag":      { "Destinations": { "d1": { "Address": "http://rag-hybride:8000/" } } }
    }
  }
}
```

- [ ] **Étape 6 : Écrire `Program.cs`**

Remplacer intégralement `src/Sorabel.ApiGateway.Api/Program.cs` :

```csharp
var builder = WebApplication.CreateBuilder(args);

builder.Configuration.AddJsonFile("appsettings.Routes.json", optional: false, reloadOnChange: true);

builder.Services
    .AddReverseProxy()
    .LoadFromConfig(builder.Configuration.GetSection("ReverseProxy"));

var app = builder.Build();

app.MapGet("/health", () => Results.Ok(new { status = "healthy" }));
app.MapReverseProxy();

app.Run();

// Rendu visible pour WebApplicationFactory<Program> dans les tests.
public partial class Program;
```

- [ ] **Étape 7 : Lancer les tests et vérifier qu'ils passent**

```bash
make test
```

Attendu : SUCCÈS. Les 6 routes atteignent leur backend, `Authorization` est relayé, `/health` répond.

- [ ] **Étape 8 : Committer**

```bash
git add src/Sorabel.ApiGateway.Api tests/Sorabel.ApiGateway.Api.Tests Sorabel.ApiGateway.sln
git commit -m "feat(api-gateway): déclare le contrat de routage des six routes

Deux plans d'adressage distincts : /api/v1 pour le trafic client,
/internal/v1 pour les appels de mcp vers ses backends. Inclut la route
JWKS interne, sans laquelle mcp devrait joindre Keycloak directement.

Le timeout d'une route externe dépasse celui de la route interne la plus
lente qu'elle déclenche, sinon la gateway abandonnerait l'appel client
pendant qu'une génération LLM facturée tourne encore."
```

---

## Tâche 4 : Correlation ID de bout en bout

**Files:**
- Create: `src/Sorabel.ApiGateway.Infrastructure/Sorabel.ApiGateway.Infrastructure.csproj`
- Create: `src/Sorabel.ApiGateway.Infrastructure/Correlation/CorrelationMiddleware.cs`
- Create: `src/Sorabel.ApiGateway.Infrastructure/Correlation/CorrelationTransform.cs`
- Modify: `src/Sorabel.ApiGateway.Api/Program.cs`
- Create: `tests/Sorabel.ApiGateway.Api.Tests/CorrelationTests.cs`

**Interfaces:**
- Consumes: `CorrelationId` (Tâche 2)
- Produces :
  - `CorrelationMiddleware` (middleware ASP.NET conventionnel, `InvokeAsync(HttpContext)`)
  - `CorrelationTransform.Register(TransformBuilderContext context) -> void`
  - `HttpContext.Items[CorrelationId.HeaderName]` contient un `CorrelationId` en aval du middleware

- [ ] **Étape 1 : Créer le projet Infrastructure**

```bash
dotnet new classlib -n Sorabel.ApiGateway.Infrastructure -o src/Sorabel.ApiGateway.Infrastructure -f net9.0
rm src/Sorabel.ApiGateway.Infrastructure/Class1.cs
dotnet sln add src/Sorabel.ApiGateway.Infrastructure
dotnet add src/Sorabel.ApiGateway.Infrastructure reference src/Sorabel.ApiGateway.Domain
dotnet add src/Sorabel.ApiGateway.Infrastructure package Yarp.ReverseProxy --version 2.3.0
dotnet add src/Sorabel.ApiGateway.Api reference src/Sorabel.ApiGateway.Infrastructure
```

Ajouter au `.csproj` de Infrastructure, dans le `<PropertyGroup>` :

```xml
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
```

Puis, pour accéder aux types ASP.NET depuis une bibliothèque de classes, ajouter dans le même `.csproj`, au niveau de `<Project>` :

```xml
  <ItemGroup>
    <FrameworkReference Include="Microsoft.AspNetCore.App" />
  </ItemGroup>
```

- [ ] **Étape 2 : Écrire les tests**

Créer `tests/Sorabel.ApiGateway.Api.Tests/CorrelationTests.cs` :

```csharp
using Sorabel.ApiGateway.Domain;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using Xunit;

namespace Sorabel.ApiGateway.Api.Tests;

[Trait("Level", "3")]
public class CorrelationTests : IClassFixture<GatewayFixture>
{
    private readonly GatewayFixture _fixture;

    public CorrelationTests(GatewayFixture fixture) => _fixture = fixture;

    private (HttpClient Client, WireMock.Server.WireMockServer Backend) Arrange()
    {
        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath("/call_tool"))
            .RespondWith(Response.Create().WithStatusCode(200));

        var client = _fixture.CreateClient(new Dictionary<string, string> { ["mcp"] = backend.Url! });
        return (client, backend);
    }

    [Fact]
    public async Task Genere_un_identifiant_quand_le_client_n_en_fournit_pas()
    {
        var (client, backend) = Arrange();

        var response = await client.GetAsync("/api/v1/mcp/call_tool");

        var renvoye = Assert.Single(response.Headers.GetValues(CorrelationId.HeaderName));
        Assert.False(string.IsNullOrWhiteSpace(renvoye));

        var recue = Assert.Single(backend.LogEntries);
        var transmis = recue.RequestMessage.Headers![CorrelationId.HeaderName].Single();
        Assert.Equal(renvoye, transmis);
    }

    [Fact]
    public async Task Propage_l_identifiant_fourni_par_l_appelant()
    {
        var (client, backend) = Arrange();
        client.DefaultRequestHeaders.Add(CorrelationId.HeaderName, "trace-de-mcp-42");

        var response = await client.GetAsync("/api/v1/mcp/call_tool");

        var recue = Assert.Single(backend.LogEntries);
        Assert.Equal("trace-de-mcp-42", recue.RequestMessage.Headers![CorrelationId.HeaderName].Single());
        Assert.Equal("trace-de-mcp-42", response.Headers.GetValues(CorrelationId.HeaderName).Single());
    }

    [Fact]
    public async Task Remplace_un_identifiant_entrant_non_conforme()
    {
        var (client, backend) = Arrange();
        client.DefaultRequestHeaders.TryAddWithoutValidation(CorrelationId.HeaderName, "valeur invalide!");

        await client.GetAsync("/api/v1/mcp/call_tool");

        var recue = Assert.Single(backend.LogEntries);
        var transmis = recue.RequestMessage.Headers![CorrelationId.HeaderName].Single();
        Assert.NotEqual("valeur invalide!", transmis);
    }
}
```

- [ ] **Étape 3 : Lancer les tests et vérifier qu'ils échouent**

```bash
dotnet test tests/Sorabel.ApiGateway.Api.Tests --filter "FullyQualifiedName~CorrelationTests"
```

Attendu : ÉCHEC — l'en-tête `X-Correlation-Id` est absent de la réponse.

- [ ] **Étape 4 : Implémenter le middleware**

Créer `src/Sorabel.ApiGateway.Infrastructure/Correlation/CorrelationMiddleware.cs` :

```csharp
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Sorabel.ApiGateway.Domain;

namespace Sorabel.ApiGateway.Infrastructure.Correlation;

/// <summary>
/// Attache un identifiant de corrélation à chaque requête : repris de l'appelant
/// s'il est conforme, généré sinon. Il est placé dans HttpContext.Items pour le
/// transform sortant, dans le scope de log, et renvoyé au client.
/// </summary>
public sealed class CorrelationMiddleware(RequestDelegate next, ILogger<CorrelationMiddleware> logger)
{
    public async Task InvokeAsync(HttpContext context)
    {
        var id = CorrelationId.FromHeaderOrNew(context.Request.Headers[CorrelationId.HeaderName]);

        context.Items[CorrelationId.HeaderName] = id;
        context.Response.Headers[CorrelationId.HeaderName] = id.Value;

        using (logger.BeginScope(new Dictionary<string, object> { ["correlation_id"] = id.Value }))
        {
            await next(context);
        }
    }
}
```

- [ ] **Étape 5 : Implémenter le transform sortant**

Créer `src/Sorabel.ApiGateway.Infrastructure/Correlation/CorrelationTransform.cs` :

```csharp
using Sorabel.ApiGateway.Domain;
using Yarp.ReverseProxy.Transforms;
using Yarp.ReverseProxy.Transforms.Builder;

namespace Sorabel.ApiGateway.Infrastructure.Correlation;

/// <summary>
/// Injecte l'identifiant de corrélation dans la requête sortante. L'en-tête
/// entrant est retiré d'abord : la valeur qui part est toujours celle validée
/// par le middleware, jamais celle fournie telle quelle par l'appelant.
/// </summary>
public static class CorrelationTransform
{
    public static void Register(TransformBuilderContext context)
    {
        context.AddRequestTransform(transformContext =>
        {
            if (transformContext.HttpContext.Items[CorrelationId.HeaderName] is CorrelationId id)
            {
                transformContext.ProxyRequest.Headers.Remove(CorrelationId.HeaderName);
                transformContext.ProxyRequest.Headers.TryAddWithoutValidation(
                    CorrelationId.HeaderName, id.Value);
            }

            return ValueTask.CompletedTask;
        });
    }
}
```

- [ ] **Étape 6 : Brancher dans `Program.cs`**

Modifier `src/Sorabel.ApiGateway.Api/Program.cs` — ajouter le `using`, le `.AddTransforms(...)` et le middleware :

```csharp
using Sorabel.ApiGateway.Infrastructure.Correlation;

var builder = WebApplication.CreateBuilder(args);

builder.Configuration.AddJsonFile("appsettings.Routes.json", optional: false, reloadOnChange: true);

builder.Services
    .AddReverseProxy()
    .LoadFromConfig(builder.Configuration.GetSection("ReverseProxy"))
    .AddTransforms(CorrelationTransform.Register);

var app = builder.Build();

app.UseMiddleware<CorrelationMiddleware>();

app.MapGet("/health", () => Results.Ok(new { status = "healthy" }));
app.MapReverseProxy();

app.Run();

public partial class Program;
```

- [ ] **Étape 7 : Lancer les tests et vérifier qu'ils passent**

```bash
make test
```

Attendu : SUCCÈS, y compris les tests de la Tâche 3 qui ne doivent pas régresser.

- [ ] **Étape 8 : Committer**

```bash
git add src tests Sorabel.ApiGateway.sln
git commit -m "feat(api-gateway): propage un identifiant de corrélation de bout en bout

L'en-tête entrant est retiré avant réémission : la valeur transmise au
backend est toujours celle validée par le middleware, jamais celle fournie
telle quelle par l'appelant."
```

---

## Tâche 5 : Résilience — le rejeu greffé dans YARP

**Files:**
- Create: `src/Sorabel.ApiGateway.Infrastructure/Resilience/RetryHandler.cs`
- Create: `src/Sorabel.ApiGateway.Infrastructure/Resilience/ResilientForwarderHttpClientFactory.cs`
- Modify: `src/Sorabel.ApiGateway.Api/Program.cs`
- Create: `tests/Sorabel.ApiGateway.Api.Tests/RetryHandlerTests.cs`

**Interfaces:**
- Consumes: `RetryDecision.CanRetry` (Tâche 1)
- Produces :
  - `RetryHandler(ILogger logger) : DelegatingHandler` — `public`, pour être testable directement
  - `ResilientForwarderHttpClientFactory(ILoggerFactory) : ForwarderHttpClientFactory`

Note d'implémentation vérifiée : `ForwarderHttpClientFactory` n'est pas scellée et expose `protected virtual HttpMessageHandler WrapHandler(ForwarderHttpClientContext, HttpMessageHandler)`. C'est le point de greffe prévu par YARP — il n'y a pas d'`HttpClient` nommé à configurer, YARP fabriquant lui-même un `HttpMessageInvoker`.

- [ ] **Étape 1 : Écrire les tests**

Créer `tests/Sorabel.ApiGateway.Api.Tests/RetryHandlerTests.cs` :

```csharp
using Microsoft.Extensions.Logging.Abstractions;
using Sorabel.ApiGateway.Infrastructure.Resilience;
using Xunit;

namespace Sorabel.ApiGateway.Api.Tests;

[Trait("Level", "2")]
public class RetryHandlerTests
{
    /// Compte les appels et rejoue le scénario demandé.
    private sealed class HandlerCompteur(Func<int, HttpResponseMessage> comportement) : HttpMessageHandler
    {
        public int Appels { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Appels++;
            return Task.FromResult(comportement(Appels));
        }
    }

    private static HttpRequestMessage Requete(bool avecCorps) =>
        new(HttpMethod.Post, "http://backend/appel")
        {
            Content = avecCorps ? new StringContent("{}") : null,
        };

    private static async Task<(int Appels, Exception? Erreur)> Envoyer(
        HttpRequestMessage requete, Func<int, HttpResponseMessage> comportement)
    {
        var inner = new HandlerCompteur(comportement);
        using var invoker = new HttpMessageInvoker(
            new RetryHandler(NullLogger.Instance) { InnerHandler = inner });

        try
        {
            await invoker.SendAsync(requete, CancellationToken.None);
            return (inner.Appels, null);
        }
        catch (Exception ex)
        {
            return (inner.Appels, ex);
        }
    }

    [Fact]
    public async Task Rejoue_deux_fois_un_echec_de_connexion_sans_corps()
    {
        var (appels, erreur) = await Envoyer(
            Requete(avecCorps: false),
            _ => throw new HttpRequestException(HttpRequestError.ConnectionError));

        Assert.Equal(3, appels); // 1 essai + 2 rejeux
        Assert.IsType<HttpRequestException>(erreur);
    }

    [Fact]
    public async Task S_arrete_des_qu_une_tentative_reussit()
    {
        var (appels, erreur) = await Envoyer(
            Requete(avecCorps: false),
            n => n < 2
                ? throw new HttpRequestException(HttpRequestError.ConnectionError)
                : new HttpResponseMessage(System.Net.HttpStatusCode.OK));

        Assert.Equal(2, appels);
        Assert.Null(erreur);
    }

    // La garantie centrale : un POST avec corps n'est jamais rejoué.
    [Fact]
    public async Task Ne_rejoue_jamais_une_requete_portant_un_corps()
    {
        var (appels, erreur) = await Envoyer(
            Requete(avecCorps: true),
            _ => throw new HttpRequestException(HttpRequestError.ConnectionError));

        Assert.Equal(1, appels);
        Assert.IsType<HttpRequestException>(erreur);
    }

    [Fact]
    public async Task Ne_rejoue_pas_une_annulation_ni_un_timeout()
    {
        var (appels, erreur) = await Envoyer(
            Requete(avecCorps: false),
            _ => throw new TaskCanceledException("délai dépassé"));

        Assert.Equal(1, appels);
        Assert.IsType<TaskCanceledException>(erreur);
    }

    [Fact]
    public async Task Ne_rejoue_pas_une_reponse_5xx_recue()
    {
        var (appels, erreur) = await Envoyer(
            Requete(avecCorps: false),
            _ => new HttpResponseMessage(System.Net.HttpStatusCode.InternalServerError));

        Assert.Equal(1, appels);
        Assert.Null(erreur);
    }
}
```

- [ ] **Étape 2 : Lancer les tests et vérifier qu'ils échouent**

```bash
dotnet test tests/Sorabel.ApiGateway.Api.Tests --filter "FullyQualifiedName~RetryHandlerTests"
```

Attendu : ÉCHEC de compilation — `RetryHandler` n'existe pas.

- [ ] **Étape 3 : Implémenter `RetryHandler`**

Créer `src/Sorabel.ApiGateway.Infrastructure/Resilience/RetryHandler.cs` :

```csharp
using Microsoft.Extensions.Logging;
using Sorabel.ApiGateway.Domain;

namespace Sorabel.ApiGateway.Infrastructure.Resilience;

/// <summary>
/// Rejoue un transfert uniquement lorsque RetryDecision l'autorise. Une
/// annulation ou un dépassement de délai remonte tel quel : la requête a pu
/// être reçue et traitée, la rejouer produirait une double exécution.
/// </summary>
public sealed class RetryHandler(ILogger logger) : DelegatingHandler
{
    private const int MaxAttempts = 3; // 1 essai + 2 rejeux

    private static readonly TimeSpan[] Backoff =
        [TimeSpan.FromMilliseconds(100), TimeSpan.FromMilliseconds(300)];

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var hasBody = request.Content is not null;

        for (var attempt = 1; ; attempt++)
        {
            try
            {
                return await base.SendAsync(request, cancellationToken);
            }
            catch (HttpRequestException ex)
                when (attempt < MaxAttempts && RetryDecision.CanRetry(ex.HttpRequestError, hasBody))
            {
                logger.LogWarning(
                    "Transfert échoué (tentative {Attempt}, {Error}) — rejeu",
                    attempt, ex.HttpRequestError);

                await Task.Delay(Backoff[attempt - 1], cancellationToken);
            }
        }
    }
}
```

- [ ] **Étape 4 : Implémenter la fabrique**

Créer `src/Sorabel.ApiGateway.Infrastructure/Resilience/ResilientForwarderHttpClientFactory.cs` :

```csharp
using Microsoft.Extensions.Logging;
using Yarp.ReverseProxy.Forwarder;

namespace Sorabel.ApiGateway.Infrastructure.Resilience;

/// <summary>
/// Greffe le RetryHandler dans la chaîne que YARP utilise pour parler aux
/// backends. YARP ne passe pas par un HttpClient nommé : il fabrique son propre
/// HttpMessageInvoker, et WrapHandler est le point d'extension prévu pour
/// l'entourer.
/// </summary>
public sealed class ResilientForwarderHttpClientFactory(ILoggerFactory loggerFactory)
    : ForwarderHttpClientFactory
{
    protected override HttpMessageHandler WrapHandler(
        ForwarderHttpClientContext context, HttpMessageHandler handler)
        => new RetryHandler(loggerFactory.CreateLogger<RetryHandler>())
        {
            InnerHandler = base.WrapHandler(context, handler),
        };
}
```

- [ ] **Étape 5 : Enregistrer la fabrique dans `Program.cs`**

Ajouter le `using` et l'enregistrement **avant** `AddReverseProxy()` :

```csharp
using Sorabel.ApiGateway.Infrastructure.Resilience;
using Yarp.ReverseProxy.Forwarder;

// …
builder.Services.AddSingleton<IForwarderHttpClientFactory, ResilientForwarderHttpClientFactory>();

builder.Services
    .AddReverseProxy()
    // …
```

- [ ] **Étape 6 : Lancer les tests et vérifier qu'ils passent**

```bash
make test
```

Attendu : SUCCÈS.

- [ ] **Étape 7 : Committer**

```bash
git add src tests
git commit -m "feat(api-gateway): greffe le rejeu des échecs de connexion dans YARP

Un POST portant un corps n'est jamais rejoué : YARP transmet le corps en
streaming via un contenu à usage unique, qu'un second essai enverrait
vide. Une annulation ou un dépassement de délai remonte tel quel, la
requête ayant pu être reçue et traitée."
```

---

## Tâche 6 : Erreurs de routage — 502/504, et relais verbatim du reste

**Files:**
- Create: `src/Sorabel.ApiGateway.Infrastructure/Errors/GatewayErrorResponse.cs`
- Create: `src/Sorabel.ApiGateway.Infrastructure/Errors/ForwarderErrorTranslator.cs`
- Create: `src/Sorabel.ApiGateway.Infrastructure/Errors/ForwarderErrorMiddleware.cs`
- Modify: `src/Sorabel.ApiGateway.Api/Program.cs`
- Create: `tests/Sorabel.ApiGateway.Api.Tests/ErrorContractTests.cs`

**Interfaces:**
- Consumes: `RoutingError`, `RoutingErrorKind`, `CorrelationId` (Tâche 2)
- Produces :
  - `GatewayErrorResponse(string ErrorCode, string Message, string CorrelationId)` sérialisé en `snake_case`
  - `ForwarderErrorTranslator.Translate(ForwarderError error) -> RoutingError?`
  - `ForwarderErrorMiddleware`

- [ ] **Étape 1 : Écrire les tests**

Créer `tests/Sorabel.ApiGateway.Api.Tests/ErrorContractTests.cs` :

```csharp
using System.Net;
using System.Text.Json;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using Xunit;

namespace Sorabel.ApiGateway.Api.Tests;

[Trait("Level", "3")]
public class ErrorContractTests : IClassFixture<GatewayFixture>
{
    private readonly GatewayFixture _fixture;

    public ErrorContractTests(GatewayFixture fixture) => _fixture = fixture;

    [Fact]
    public async Task Backend_eteint_donne_un_502_au_format_du_contrat()
    {
        // Port fermé : personne n'écoute, la connexion est refusée.
        var client = _fixture.CreateClient(new Dictionary<string, string>
        {
            ["mcp"] = "http://127.0.0.1:1/",
        });

        var response = await client.GetAsync("/api/v1/mcp/call_tool");

        Assert.Equal(HttpStatusCode.BadGateway, response.StatusCode);

        using var payload = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var racine = payload.RootElement;

        Assert.Equal("BACKEND_UNREACHABLE", racine.GetProperty("error_code").GetString());
        Assert.False(string.IsNullOrWhiteSpace(racine.GetProperty("message").GetString()));
        Assert.False(string.IsNullOrWhiteSpace(racine.GetProperty("correlation_id").GetString()));
    }

    [Fact]
    public async Task Le_message_d_erreur_ne_revele_pas_la_topologie_interne()
    {
        var client = _fixture.CreateClient(new Dictionary<string, string>
        {
            ["mcp"] = "http://127.0.0.1:1/",
        });

        var corps = await (await client.GetAsync("/api/v1/mcp/call_tool")).Content.ReadAsStringAsync();

        using var payload = JsonDocument.Parse(corps);
        var message = payload.RootElement.GetProperty("message").GetString()!;

        Assert.DoesNotContain("127.0.0.1", message);
        Assert.DoesNotContain("mcp", message, StringComparison.OrdinalIgnoreCase);
    }

    // Garde-fou central : une réponse effectivement reçue n'est JAMAIS réécrite.
    // Sans quoi le client ne pourrait plus distinguer un refus d'autorisation
    // (403 de mcp) d'une panne, et le mécanisme isError/reason d'E1/E5 serait
    // détruit.
    [Theory]
    [InlineData(403, "UNAUTHORIZED_TOOL")]
    [InlineData(404, "NOT_FOUND_IN_CORPUS")]
    [InlineData(500, "INTERNAL")]
    [InlineData(503, "OVERLOADED")]
    public async Task Relaie_verbatim_toute_reponse_recue_du_backend(int statut, string codeMetier)
    {
        var corpsBackend = $$"""{"error_code":"{{codeMetier}}","message":"venant du backend"}""";

        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath("/call_tool"))
            .RespondWith(Response.Create()
                .WithStatusCode(statut)
                .WithHeader("Content-Type", "application/json")
                .WithBody(corpsBackend));

        var client = _fixture.CreateClient(new Dictionary<string, string> { ["mcp"] = backend.Url! });

        var response = await client.GetAsync("/api/v1/mcp/call_tool");

        Assert.Equal(statut, (int)response.StatusCode);
        Assert.Equal(corpsBackend, await response.Content.ReadAsStringAsync());
    }
}
```

- [ ] **Étape 2 : Lancer les tests et vérifier qu'ils échouent**

```bash
dotnet test tests/Sorabel.ApiGateway.Api.Tests --filter "FullyQualifiedName~ErrorContractTests"
```

Attendu : ÉCHEC — le backend éteint produit une réponse 502 vide, sans corps JSON.

- [ ] **Étape 3 : Implémenter le DTO**

Créer `src/Sorabel.ApiGateway.Infrastructure/Errors/GatewayErrorResponse.cs` :

```csharp
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
```

- [ ] **Étape 4 : Implémenter le traducteur**

Créer `src/Sorabel.ApiGateway.Infrastructure/Errors/ForwarderErrorTranslator.cs` :

```csharp
using Sorabel.ApiGateway.Domain;
using Yarp.ReverseProxy.Forwarder;

namespace Sorabel.ApiGateway.Infrastructure.Errors;

/// <summary>
/// Traduit un échec de transfert YARP en erreur de routage du domaine.
/// Retourne null quand la gateway ne doit rien fabriquer — soit qu'il n'y ait
/// pas d'erreur, soit que le client ait abandonné, soit que la réponse ait déjà
/// commencé à partir.
/// </summary>
public static class ForwarderErrorTranslator
{
    public static RoutingError? Translate(ForwarderError error) => error switch
    {
        ForwarderError.None => null,

        // Le backend n'a pas répondu dans le délai de la route.
        ForwarderError.RequestTimedOut
            or ForwarderError.UpgradeActivityTimeout
            => new RoutingError(RoutingErrorKind.BackendTimeout),

        // Aucune connexion établie, ou aucune destination configurée.
        ForwarderError.Request
            or ForwarderError.RequestCreation
            or ForwarderError.NoAvailableDestinations
            or ForwarderError.RequestBodyDestination
            or ForwarderError.UpgradeRequestDestination
            => new RoutingError(RoutingErrorKind.BackendUnreachable),

        // Le client a abandonné, ou la réponse était déjà en cours d'envoi :
        // il n'y a rien à écrire.
        _ => null,
    };
}
```

- [ ] **Étape 5 : Implémenter le middleware**

Créer `src/Sorabel.ApiGateway.Infrastructure/Errors/ForwarderErrorMiddleware.cs` :

```csharp
using Microsoft.AspNetCore.Http;
using Sorabel.ApiGateway.Domain;
using Yarp.ReverseProxy.Forwarder;

namespace Sorabel.ApiGateway.Infrastructure.Errors;

/// <summary>
/// Fabrique une réponse d'erreur uniquement lorsqu'aucune réponse n'a été reçue
/// du backend. Toute réponse effectivement reçue — y compris 403 ou 500 — a déjà
/// été relayée verbatim par YARP et ne passe pas par ici.
/// </summary>
public sealed class ForwarderErrorMiddleware(RequestDelegate next)
{
    public async Task InvokeAsync(HttpContext context)
    {
        await next(context);

        var feature = context.Features.Get<IForwarderErrorFeature>();
        if (feature is null || context.Response.HasStarted)
        {
            return;
        }

        var error = ForwarderErrorTranslator.Translate(feature.Error);
        if (error is null)
        {
            return;
        }

        var correlationId = context.Items[CorrelationId.HeaderName] is CorrelationId id
            ? id.Value
            : string.Empty;

        context.Response.Clear();
        context.Response.StatusCode = error.StatusCode;
        context.Response.Headers[CorrelationId.HeaderName] = correlationId;

        await context.Response.WriteAsJsonAsync(
            new GatewayErrorResponse(error.ErrorCode, error.Message, correlationId));
    }
}
```

- [ ] **Étape 6 : Brancher dans `Program.cs`**

Ajouter le `using Sorabel.ApiGateway.Infrastructure.Errors;` et insérer le middleware **après** `CorrelationMiddleware` (il doit voir l'identifiant déjà posé) et **avant** `MapReverseProxy` :

```csharp
app.UseMiddleware<CorrelationMiddleware>();
app.UseMiddleware<ForwarderErrorMiddleware>();
```

- [ ] **Étape 7 : Lancer les tests et vérifier qu'ils passent**

```bash
make test
```

Attendu : SUCCÈS. En particulier les 4 cas de `Relaie_verbatim_toute_reponse_recue_du_backend`.

- [ ] **Étape 8 : Committer**

```bash
git add src tests
git commit -m "feat(api-gateway): normalise les erreurs de routage en 502/504

La gateway ne fabrique une réponse que lorsqu'aucune réponse n'a été reçue.
Une réponse effectivement reçue est relayée verbatim, y compris 403 et 500 :
la réécrire empêcherait le client de distinguer un refus d'autorisation
d'une panne et détruirait le mécanisme isError/reason d'E1 et E5.

Le message d'erreur ne nomme aucun backend, pour ne pas cartographier la
topologie interne via la réponse."
```

---

## Tâche 7 : Journalisation sans fuite

**Files:**
- Create: `src/Sorabel.ApiGateway.Infrastructure/Logging/RequestLoggingMiddleware.cs`
- Modify: `src/Sorabel.ApiGateway.Api/Program.cs`
- Create: `tests/Sorabel.ApiGateway.Api.Tests/LoggingTests.cs`
- Modify: `tests/Sorabel.ApiGateway.Api.Tests/GatewayFixture.cs`

**Interfaces:**
- Consumes: `CorrelationId`, `BackendId`, `SensitiveHeaders` (Tâche 2)
- Produces : `RequestLoggingMiddleware`, et sur `GatewayFixture` : `CreateClient(destinations, out List<string> journal)`

- [ ] **Étape 1 : Étendre le harnais pour capturer les logs**

Ajouter dans `tests/Sorabel.ApiGateway.Api.Tests/GatewayFixture.cs` :

```csharp
    /// Variante qui capture toutes les lignes de log émises par la gateway.
    public HttpClient CreateClient(
        IReadOnlyDictionary<string, string> destinations,
        out List<string> journal)
    {
        var lignes = new List<string>();
        journal = lignes;

        var overrides = destinations.ToDictionary(
            kv => $"ReverseProxy:Clusters:{kv.Key}:Destinations:d1:Address",
            kv => (string?)kv.Value);

        var factory = new WebApplicationFactory<Program>()
            .WithWebHostBuilder(builder =>
            {
                builder.ConfigureAppConfiguration((_, config) => config.AddInMemoryCollection(overrides));
                builder.ConfigureLogging(logging =>
                {
                    logging.ClearProviders();
                    logging.SetMinimumLevel(LogLevel.Debug);
                    logging.AddProvider(new ListLoggerProvider(lignes));
                });
            });

        _factories.Add(factory);
        return factory.CreateClient();
    }
```

Créer `tests/Sorabel.ApiGateway.Api.Tests/ListLoggerProvider.cs` :

```csharp
using Microsoft.Extensions.Logging;

namespace Sorabel.ApiGateway.Api.Tests;

/// Capture chaque ligne de log formatée, pour pouvoir affirmer ce qui n'y figure pas.
public sealed class ListLoggerProvider(List<string> lignes) : ILoggerProvider
{
    public ILogger CreateLogger(string categoryName) => new ListLogger(lignes);

    public void Dispose() { }

    private sealed class ListLogger(List<string> lignes) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(
            LogLevel logLevel, EventId eventId, TState state, Exception? exception,
            Func<TState, Exception?, string> formatter)
        {
            lock (lignes)
            {
                lignes.Add(formatter(state, exception));
            }
        }
    }
}
```

Les `using` nécessaires sont déjà présents en tête de `GatewayFixture.cs` (Tâche 3, étape 2).

- [ ] **Étape 2 : Écrire les tests**

Créer `tests/Sorabel.ApiGateway.Api.Tests/LoggingTests.cs` :

```csharp
using System.Net.Http.Headers;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using Xunit;

namespace Sorabel.ApiGateway.Api.Tests;

[Trait("Level", "3")]
public class LoggingTests : IClassFixture<GatewayFixture>
{
    private readonly GatewayFixture _fixture;

    public LoggingTests(GatewayFixture fixture) => _fixture = fixture;

    [Fact]
    public async Task Journalise_une_ligne_par_requete_relayee()
    {
        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath("/call_tool"))
            .RespondWith(Response.Create().WithStatusCode(200));

        var client = _fixture.CreateClient(
            new Dictionary<string, string> { ["mcp"] = backend.Url! }, out var journal);

        await client.GetAsync("/api/v1/mcp/call_tool");

        var ligne = Assert.Single(journal, l => l.Contains("backend=mcp"));
        Assert.Contains("status=200", ligne);
        Assert.Contains("method=GET", ligne);
        Assert.Contains("/api/v1/mcp/call_tool", ligne);
    }

    // Non-négociable de sécurité : le JWT traverse la gateway sans jamais
    // apparaître dans un log, sous aucune forme.
    [Fact]
    public async Task Ne_journalise_jamais_le_jeton_ni_l_entete_Authorization()
    {
        const string jeton = "eyJhbGciOiJSUzI1NiJ9.SECRET-A-NE-PAS-JOURNALISER.signature";

        var backend = _fixture.StartBackend();
        backend
            .Given(Request.Create().WithPath("/call_tool"))
            .RespondWith(Response.Create().WithStatusCode(200));

        var client = _fixture.CreateClient(
            new Dictionary<string, string> { ["mcp"] = backend.Url! }, out var journal);
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", jeton);

        await client.GetAsync("/api/v1/mcp/call_tool");

        var tout = string.Join("\n", journal);
        Assert.DoesNotContain("SECRET-A-NE-PAS-JOURNALISER", tout);
        Assert.DoesNotContain(jeton, tout);
        Assert.DoesNotContain("Bearer", tout);
    }
}
```

- [ ] **Étape 3 : Lancer les tests et vérifier qu'ils échouent**

```bash
dotnet test tests/Sorabel.ApiGateway.Api.Tests --filter "FullyQualifiedName~LoggingTests"
```

Attendu : ÉCHEC — aucune ligne ne contient `backend=mcp`.

- [ ] **Étape 4 : Implémenter le middleware de journalisation**

Créer `src/Sorabel.ApiGateway.Infrastructure/Logging/RequestLoggingMiddleware.cs` :

```csharp
using System.Diagnostics;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Sorabel.ApiGateway.Domain;
using Yarp.ReverseProxy.Model;

namespace Sorabel.ApiGateway.Infrastructure.Logging;

/// <summary>
/// Une ligne structurée par requête relayée : identifiant de corrélation,
/// méthode, chemin entrant, backend, statut, durée.
///
/// Aucun en-tête n'est journalisé — c'est une liste d'autorisation de champs,
/// pas une liste de blocage à tenir à jour. SensitiveHeaders documente ce qui
/// ne doit jamais fuiter si un futur contributeur ajoutait des en-têtes ici.
/// </summary>
public sealed class RequestLoggingMiddleware(RequestDelegate next, ILogger<RequestLoggingMiddleware> logger)
{
    public async Task InvokeAsync(HttpContext context)
    {
        var chrono = Stopwatch.StartNew();
        var chemin = context.Request.Path.Value ?? "/";
        var methode = context.Request.Method;

        try
        {
            await next(context);
        }
        finally
        {
            chrono.Stop();

            // GetReverseProxyFeature() lève si la requête n'a pas été routée
            // (ex. /health) : on lit la feature directement.
            var clusterId = context.Features.Get<IReverseProxyFeature>()?.Cluster?.Config.ClusterId;
            var backend = BackendId.TryFromClusterId(clusterId, out var id) ? id.Value : "-";

            var correlationId = context.Items[CorrelationId.HeaderName] is CorrelationId cid
                ? cid.Value
                : "-";

            logger.LogInformation(
                "correlation_id={CorrelationId} method={Method} path={Path} backend={Backend} status={Status} duration_ms={Duration}",
                correlationId, methode, chemin, backend, context.Response.StatusCode,
                chrono.ElapsedMilliseconds);
        }
    }
}
```

- [ ] **Étape 5 : Brancher dans `Program.cs`**

Ajouter `using Sorabel.ApiGateway.Infrastructure.Logging;` et insérer **juste après** `CorrelationMiddleware`, pour que l'identifiant soit disponible et que la durée mesurée englobe tout le traitement :

```csharp
app.UseMiddleware<CorrelationMiddleware>();
app.UseMiddleware<RequestLoggingMiddleware>();
app.UseMiddleware<ForwarderErrorMiddleware>();
```

- [ ] **Étape 6 : Lancer les tests et vérifier qu'ils passent**

```bash
make test
```

Attendu : SUCCÈS.

- [ ] **Étape 7 : Committer**

```bash
git add src tests
git commit -m "feat(api-gateway): journalise chaque requête relayée sans fuite

Les champs journalisés sont une liste d'autorisation, pas une liste de
blocage : aucun en-tête n'est écrit, donc le JWT ne peut pas fuiter par
oubli. Un test vérifie qu'aucune trace du jeton n'apparaît dans le journal."
```

---

## Tâche 8 : Packaging Docker et test de niveau 4

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`
- Create: `.env.example`
- Create: `tests/Sorabel.ApiGateway.E2E.Tests/Sorabel.ApiGateway.E2E.Tests.csproj`
- Create: `tests/Sorabel.ApiGateway.E2E.Tests/TraverseeTests.cs`
- Modify: `Makefile`

**Interfaces:**
- Consumes: l'application complète des tâches 3 à 7
- Produces: image `api-gateway`, service compose `api-gateway` exposé sur `8080`

Le backend factice est l'image `traefik/whoami`, qui renvoie en clair la ligne de requête et les en-têtes qu'elle a reçus. Elle permet donc d'affirmer, depuis l'extérieur, que le préfixe a bien été retiré et que le correlation ID est bien arrivé.

- [ ] **Étape 1 : Écrire le Dockerfile**

Créer `Dockerfile` :

```dockerfile
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
```

Note : l'image `aspnet:9.0` ne contient ni `curl` ni `wget`. Plutôt que d'en installer un, `Program.cs` reconnaît l'argument `--healthcheck` (étape 3).

- [ ] **Étape 2 : Écrire `.dockerignore`, `docker-compose.yml` et `.env.example`**

Créer `.dockerignore` :

```
**/bin/
**/obj/
tests/
docs/
.git/
```

Créer `docker-compose.yml` :

```yaml
name: sorabel-api-gateway

services:
  api-gateway:
    build: .
    image: api-gateway
    ports:
      - "${API_GATEWAY_PORT:-8080}:8080"
    environment:
      # En local, seul le backend factice est joignable ; les autres clusters
      # gardent leur adresse par défaut et produisent un 502, ce qui est le
      # comportement attendu tant qu'ils n'existent pas.
      ReverseProxy__Clusters__text2sql__Destinations__d1__Address: http://backend-factice/
    depends_on:
      backend-factice:
        condition: service_started

  backend-factice:
    image: traefik/whoami:v1.10
    # Renvoie en clair la ligne de requête et les en-têtes reçus : permet de
    # vérifier de l'extérieur que le préfixe a été retiré et que le correlation
    # ID est bien arrivé.
```

Créer `.env.example` :

```
# Port publié par la gateway sur l'hôte.
API_GATEWAY_PORT=8080
```

- [ ] **Étape 3 : Ajouter le mode healthcheck dans `Program.cs`**

Insérer tout en haut de `src/Sorabel.ApiGateway.Api/Program.cs`, avant `var builder = ...` :

```csharp
// Sonde de santé invoquée par le HEALTHCHECK Docker : l'image aspnet ne
// contient ni curl ni wget, on réutilise donc le binaire lui-même.
if (args.Contains("--healthcheck"))
{
    using var sonde = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
    try
    {
        var reponse = await sonde.GetAsync("http://localhost:8080/health");
        return reponse.IsSuccessStatusCode ? 0 : 1;
    }
    catch (HttpRequestException)
    {
        return 1;
    }
}
```

Et remplacer la dernière ligne `app.Run();` par :

```csharp
app.Run();
return 0;
```

- [ ] **Étape 4 : Écrire le test de niveau 4**

```bash
dotnet new xunit -n Sorabel.ApiGateway.E2E.Tests -o tests/Sorabel.ApiGateway.E2E.Tests -f net9.0
rm tests/Sorabel.ApiGateway.E2E.Tests/UnitTest1.cs
dotnet sln add tests/Sorabel.ApiGateway.E2E.Tests
```

Créer `tests/Sorabel.ApiGateway.E2E.Tests/TraverseeTests.cs` :

```csharp
using System.Net;
using Xunit;

namespace Sorabel.ApiGateway.E2E.Tests;

/// <summary>
/// Niveau 4 : la gateway telle qu'elle sera déployée, dans son conteneur, avec
/// sa configuration réelle. Prouve ce que les niveaux 1 à 3 ne peuvent pas —
/// que l'image se construit, se configure et démarre.
///
/// Suppose `make docker-up` déjà exécuté (make test-e2e s'en charge).
/// </summary>
[Trait("Category", "E2E")]
public class TraverseeTests
{
    private static readonly string BaseUrl =
        Environment.GetEnvironmentVariable("API_GATEWAY_URL") ?? "http://localhost:8080";

    private static HttpClient Client() => new() { BaseAddress = new Uri(BaseUrl), Timeout = TimeSpan.FromSeconds(20) };

    [Fact]
    public async Task La_gateway_demarree_repond_sur_health()
    {
        using var client = Client();

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task Une_requete_traverse_reellement_jusqu_au_backend()
    {
        using var client = Client();

        var response = await client.GetAsync("/internal/v1/text2sql/generate");
        var corps = await response.Content.ReadAsStringAsync();

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        // whoami renvoie la ligne de requête reçue : le préfixe doit avoir été retiré.
        Assert.Contains("GET /generate", corps);
        Assert.DoesNotContain("/internal/v1/text2sql", corps);

        // et le correlation ID doit être arrivé jusqu'à lui.
        Assert.Contains("X-Correlation-Id:", corps, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Un_backend_absent_donne_un_502_au_format_du_contrat()
    {
        using var client = Client();

        var response = await client.GetAsync("/internal/v1/rag/search");
        var corps = await response.Content.ReadAsStringAsync();

        Assert.Equal(HttpStatusCode.BadGateway, response.StatusCode);
        Assert.Contains("BACKEND_UNREACHABLE", corps);
        Assert.Contains("correlation_id", corps);
    }
}
```

- [ ] **Étape 5 : Compléter le Makefile**

Remplacer la cible `test-e2e` par une version qui gère le cycle de vie des conteneurs :

```makefile
test-e2e:
	docker compose up -d --build --wait
	dotnet test --filter "Category=E2E" ; status=$$? ; docker compose down ; exit $$status
```

- [ ] **Étape 6 : Vérifier**

```bash
make docker-build
make test-e2e
```

Attendu : l'image se construit, les 3 tests passent, les conteneurs sont arrêtés à la fin.

Puis vérifier que le niveau 4 reste bien exclu du cycle rapide :

```bash
docker compose down
make test
```

Attendu : SUCCÈS **sans** Docker démarré — aucun test E2E n'a été exécuté.

- [ ] **Étape 7 : Committer**

```bash
git add Dockerfile docker-compose.yml .dockerignore .env.example tests/Sorabel.ApiGateway.E2E.Tests Makefile src Sorabel.ApiGateway.sln
git commit -m "feat(api-gateway): conteneurise la gateway et ajoute le test de niveau 4

Le HEALTHCHECK réutilise le binaire de l'application via --healthcheck :
l'image aspnet ne contient ni curl ni wget, et en installer un pour cela
seul alourdirait l'image sans raison.

make test-e2e démarre le compose, exécute les seuls tests marqués E2E et
arrête les conteneurs même en cas d'échec."
```

---

## Tâche 9 : Documentation et conventions de la solution

Ferme les travaux connexes recensés au §10 de la spec.

**Files:**
- Modify: `.claude/rules/routing-proxy.md`
- Modify: `.claude/commands/new-route.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `../.claude/rules/csharp-clean-architecture.md` (référence à la structure retenue)

- [ ] **Étape 1 : Remplir `.claude/rules/routing-proxy.md`**

Remplacer le TODO par le contrat effectif :

```markdown
# Routage/proxy — api-gateway

Conventions de routage pur — **pas de logique RBAC ici** (cf. `mcp/`).

## Plan d'adressage

Deux espaces distincts, qui matérialisent la séparation north-south /
service-to-service.

| Route entrante | Cluster | Timeout | Appelée par |
|---|---|---|---|
| `/api/v1/auth/{**rest}` | `idp` | 10 s | Clients (obtention du JWT) |
| `/api/v1/mcp/{**rest}` | `mcp` | 120 s | Clients (`list_tools`, `call_tool`) |
| `/internal/v1/auth/{**rest}` | `idp` | 10 s | `mcp` (récupération JWKS) |
| `/internal/v1/text2sql/{**rest}` | `text2sql` | 90 s | `mcp` (`ask_database`) |
| `/internal/v1/sql/{**rest}` | `sql` | 30 s | `mcp` (`run_sql_query`, tools figés) |
| `/internal/v1/rag/{**rest}` | `rag` | 30 s | `mcp` (`search_documents` et briques) |

## Règles

- Le préfixe est **toujours** retiré avant transmission (`PathRemovePrefix`) :
  les backends n'ont pas à savoir qu'une gateway existe.
- Le timeout d'une route externe doit **dépasser** celui de la route interne la
  plus lente qu'elle peut déclencher. Sinon la gateway abandonne l'appel client
  pendant qu'un traitement facturé tourne encore côté backend.
- Les adresses de clusters sont surchargeables par variable d'environnement
  (`ReverseProxy__Clusters__<id>__Destinations__d1__Address`), jamais figées.
- `Authorization` est relayé octet pour octet et n'est jamais lu.
- Le rejeu ne s'applique qu'aux échecs de connexion **sans corps de requête**
  (cf. `Domain/RetryDecision.cs`).
- Toute réponse reçue d'un backend est relayée verbatim — la gateway ne fabrique
  une réponse que lorsqu'il n'y en a aucune.

Détail et justification : `docs/superpowers/specs/2026-09-07-api-gateway-design.md`.
```

- [ ] **Étape 2 : Implémenter `/new-route`**

Remplacer le contenu de `.claude/commands/new-route.md` :

```markdown
---
description: Scaffold une route proxifiée vers un backend
---

# /new-route

Ajoute une route de routage pur, conformément à `.claude/rules/routing-proxy.md`.

Demander à l'utilisateur, s'ils ne sont pas fournis en argument :

1. **Plan** : `/api/v1` (appelé par un client) ou `/internal/v1` (appelé par `mcp`) ?
2. **Backend cible** : `idp`, `mcp`, `text2sql`, `sql`, `rag`.
3. **Segment de route** et **timeout**.

Puis :

1. Ajouter la paire route/cluster dans
   `src/Sorabel.ApiGateway.Api/appsettings.Routes.json`, avec un
   `PathRemovePrefix` correspondant au préfixe complet.
2. Vérifier la règle d'imbrication des timeouts : si cette route peut être
   déclenchée par une route externe, le timeout de cette dernière doit être
   supérieur. Le signaler si ce n'est pas le cas.
3. Ajouter la ligne correspondante dans `RoutingContractTests.Routes`
   (`tests/Sorabel.ApiGateway.Api.Tests/RoutingContractTests.cs`) — le test est
   paramétré, une ligne suffit.
4. Ajouter la ligne dans le tableau de `.claude/rules/routing-proxy.md`.
5. Lancer `make test` et vérifier que la nouvelle route passe.

Ne jamais ajouter de code de routage impératif : une route est une entrée de
configuration, rien d'autre.
```

- [ ] **Étape 3 : Mettre à jour `CLAUDE.md`**

Dans `api-gateway/CLAUDE.md`, section « Critères de succès », remplacer la première puce par :

```markdown
- `make build && make test && make lint` passent, et `make test-e2e` passe avec Docker démarré
```

Aucun import `@../.claude/rules/docker-conventions.md` n'est présent actuellement dans `api-gateway/CLAUDE.md` ; si une convention Docker transverse est souhaitée, elle devra être ajoutée via une PR dédiée.

- [ ] **Étape 4 : Mettre à jour le README**

Dans `api-gateway/README.md`, section « Démarrage rapide », ajouter après `make test` :

```
make test-e2e      # tests de bout en bout (démarre les conteneurs)
```

Et remplacer la section « Configuration des routes » par un renvoi vers
`.claude/rules/routing-proxy.md` pour la table des routes.

- [ ] **Étape 5 : Vérifier l'ensemble**

```bash
make build && make test && make lint
make docker-build && make test-e2e
```

Attendu : tout passe.

- [ ] **Étape 6 : Committer et ouvrir la PR**

```bash
git add .claude CLAUDE.md README.md
git commit -m "docs(api-gateway): documente le contrat de routage et implémente /new-route

Retire l'import de ../.claude/rules/docker-conventions.md : le fichier
n'existe pas, l'import était mort et chargé à chaque session."

git push -u origin feat/api-gateway/mvp
gh pr create --title "feat(api-gateway): implémente le MVP du hub de routage" --body "$(cat <<'CORPS'
## Contexte

Premier incrément d'`api-gateway`, hub de routage pur de la solution Sorabel.
Design validé : `docs/superpowers/specs/2026-09-07-api-gateway-design.md`.

## Changements

- Contrat de routage des 6 routes en configuration déclarative YARP, deux plans
  (`/api/v1` pour les clients, `/internal/v1` pour les appels de `mcp`), avec la
  route JWKS interne et la règle d'imbrication des timeouts.
- Correlation ID `X-Correlation-Id` propagé de bout en bout.
- Rejeu restreint aux échecs de connexion sans corps de requête.
- Erreurs de routage normalisées en 502/504 ; toute réponse reçue d'un backend
  est relayée verbatim.
- Journalisation d'une ligne par requête, sans aucun en-tête.
- Image Docker et tests de niveau 4.

## Comment tester

```bash
cd src/api-gateway
make build && make test && make lint
make docker-build && make test-e2e
```

## Non-négociables respectés

Aucune ligne ne lit ou n'interprète un claim JWT, un rôle ou la matrice RBAC —
vérifiable par `grep -rniE "claim|role|profile|rbac" src/ --include=*.cs`.
CORPS
)"
```

---

## Vérification finale (avant de déclarer terminé)

Ne rien affirmer sans avoir vu la sortie de ces commandes.

```bash
cd src/api-gateway
make build && make test && make lint
make docker-build && make test-e2e
```

Puis vérifier à la main les critères d'acceptation de la spec qu'aucun test ne couvre :

```bash
# Aucune interprétation de JWT, de rôle ou de profil dans le code de production.
grep -rniE "claim|role|profile|rbac|authoriz" src/ --include=*.cs

# Le Domain ne référence aucun paquet NuGet.
grep -n "PackageReference" src/Sorabel.ApiGateway.Domain/*.csproj
```

Attendu : la première commande ne remonte que des occurrences dans des commentaires expliquant ce que la gateway **ne fait pas** ; la seconde ne remonte rien.

---

## Notes de vérification (préparation du plan)

Ces points ont été validés par compilation réelle contre `Yarp.ReverseProxy` 2.3.0 et le SDK .NET 9.0.202, pas déduits de la documentation :

- `RouteConfig.Timeout` existe — le champ `"Timeout"` en configuration de route est valide.
- `ForwarderHttpClientFactory` n'est pas scellée et expose `protected virtual WrapHandler(ForwarderHttpClientContext, HttpMessageHandler)`.
- `AddTransforms(Action<TransformBuilderContext>)` et `TransformBuilderContextFuncExtensions.AddRequestTransform` existent dans `Yarp.ReverseProxy.Transforms`.
- `IForwarderErrorFeature` expose `Error` et `Exception` ; les valeurs de `ForwarderError` utilisées dans le traducteur existent toutes.
- `HttpRequestException.HttpRequestError` (.NET 8+) fournit `ConnectionError` et `NameResolutionError` — base de `RetryDecision`, plus fiable que l'inspection d'une `SocketException` interne.
- `GetReverseProxyFeature()` **lève** quand la requête n'a pas été routée par le proxy (`/health`) : le middleware de journalisation lit `context.Features.Get<IReverseProxyFeature>()` à la place.
