# kcwarden — Keycloak realm-configuration security auditor

Build **kcwarden**, a Python command-line tool that statically audits a
[Keycloak](https://www.keycloak.org/) **realm-export JSON file** and reports
security misconfigurations as structured *findings*. Each finding is produced by a
named *auditor* that inspects one realm / client / identity-provider / client-scope
object and flags a specific weakness (missing PKCE, disabled SAML signatures,
wildcard redirect URIs, weak password policy, …).

The tool is purely offline and read-only: it parses a single JSON export (the same
format produced by Keycloak's *Partial Export* / `kc.sh export`) and writes a report.
It must not contact any network service during an audit.

## Dependencies

- Python 3.10+. You may use the standard library plus these packages, which are
  **already installed** (the environment is offline — do not install anything):
  `requests`, `pyyaml` (imported as `yaml`), `rich`.
- The project must be installable offline with `pip install -e .` from a
  `pyproject.toml` / `setup.py`. Installation **must expose a console-script entry
  point named `kcwarden`** on `PATH` (the tests invoke the `kcwarden` binary
  directly). `python -m kcwarden` should also work.

## Package structure

The tests do not import the package directly; they invoke the installed `kcwarden`
console command via `subprocess`. You are free to choose the internal module layout.
The only hard requirement is the `kcwarden` entry point and the CLI contract below.

## Command-line interface

A single subcommand is exercised by the tests:

```
kcwarden audit <input_file> [options]
```

- `input_file` (positional, required): path to the Keycloak realm-export JSON file.
- `-f`, `--format {txt,csv,json}`: output format. Default `txt`.
- `-o`, `--output <path>`: write the report to a file. Default is stdout (`-`).
- `-s`, `--min-severity {INFO,LOW,MEDIUM,HIGH,CRITICAL}`: drop findings whose
  severity is below the given level (uppercase choices). When omitted, all findings
  are reported (effective minimum = `INFO`). Filtering is inclusive: `--min-severity
  MEDIUM` keeps `Medium`, `High` and `Critical`.
- `--auditors <ClassName> [<ClassName> ...]`: run only the named auditors. The names
  are the auditor **class names** (= the `reporting_auditor` field, see the catalog
  below), matched exactly and case-sensitively. When omitted, all auditors run.
- `--fail-on-findings`: process exit code is **42** when at least one finding remains
  after severity filtering; otherwise the exit code is **0**. Without this flag the
  exit code is **0 even when findings are reported**.
- `--ignore-disabled-clients`: skip client auditors for clients whose `enabled` is
  `false`.
- `-c` / `--config <path>`: a YAML config file. Its main purpose is to enable the
  **monitor checks** (see "Monitor checks" below); it can also hold per-auditor
  allowlists. When omitted, only the always-on auditors run.

The `audit` subcommand exits `0` on a successful run (with or without findings),
unless `--fail-on-findings` applies as described.

A second subcommand is also exercised:

```
kcwarden review <input_file> [-o <path>]
```

`review` reads the same realm-export JSON and emits a **CSV service-account ⇄ role
matrix** (described in its own section below). `-o` / `--output` defaults to stdout.
It is offline and read-only.

The `download` and `generate-config-template` subcommands are **out of scope** — do
not implement anything requiring network/Keycloak access.

## Finding output schema

A finding describes one problem found on one Keycloak object.

### JSON format (`--format json`)

Output is a JSON array (`[]` when empty). Each finding is an object with **exactly**
these keys:

| key                 | meaning |
|---------------------|---------|
| `fingerprint`       | a stable, deterministic identifier string for the finding (e.g. a hex digest derived from realm + entity + entity type + auditor + details). Its exact value is not asserted, but the key must be present and non-empty. |
| `severity`          | one of the strings `"Info"`, `"Low"`, `"Medium"`, `"High"`, `"Critical"`. |
| `realm`             | the audited realm's name (the export's top-level `realm` field). |
| `entity`            | the name of the offending object (see entity rules below). |
| `entity_type`       | the kind of offending object. Audit findings use `"Realm"`, `"Client"`, `"IdentityProvider"`, or `"ClientScope"`; the config-driven monitors also report the additional entity types named in their own catalog entries (see "Monitor checks"). |
| `reporting_auditor` | the auditor's class name (the catalog name below). |
| `short_description` | a brief human-readable summary. |
| `long_description`  | a longer human-readable explanation. |
| `reference`         | a reference/URL string (may be empty). |
| `additional_details`| a JSON object with auditor-specific structured context (`{}` when none). |

`short_description`, `long_description` and `reference` are free text — their wording
is not asserted (only that the keys exist). `additional_details` content **is**
asserted for a few auditors; those keys are listed in the catalog.

**Entity naming rules** (`entity` / `entity_type`):

- Realm-level findings: `entity` = the realm name, `entity_type` = `"Realm"`.
- Client findings: `entity` = the client's `clientId`, `entity_type` = `"Client"`.
- Identity-provider findings: `entity` = the IdP's `alias`, `entity_type` =
  `"IdentityProvider"`.
- Client-scope findings: `entity` = the scope's `name`, `entity_type` =
  `"ClientScope"`.

Names are **not** module-qualified or otherwise decorated — use the raw values from
the export.

### CSV format (`--format csv`)

A header row followed by one row per finding. The columns are the ten finding fields
above (same names). Use a standard comma-separated dialect with a single header row.

### txt format (default)

Human-readable table. Not asserted by the tests; any readable rendering is fine
(e.g. a `rich` table). Prints a friendly "no issues" message when there are no
findings.

## `review` output: the service-account ⇄ role matrix

`kcwarden review <export>` emits a CSV matrix that shows, for every role in the realm,
which service accounts hold it and how:

- **Header row:** the literal string `role`, followed by one column per service
  account — the `username` of every entry in `users` (i.e. every `service-account-…`).
- **Data rows:** one row per role. Realm roles come first, then client roles. The
  first cell (the `role` column) is the role's label: `realm.<roleName>` for a realm
  role, `<clientName>.<roleName>` for a client role.
- **Cells:** for each (role, service-account) pair, the cell is:
  - `"role"` — the account holds the role **directly** (the role name is in its
    `realmRoles`/`clientRoles`) **or** through a composite role: any role the account
    holds that transitively *contains* this role via its `composites` (composite
    expansion is recursive — a composite of a composite counts).
  - `"group"` — the account is a member (by group `path`, in its `groups` list) of a
    group whose **effective** roles include this role. A group's effective roles are
    its own `realmRoles`/`clientRoles` plus all roles inherited from ancestor groups
    (a subgroup inherits its parents' roles), and composite expansion applies to a
    group's roles as well.
  - empty string — the account does not hold the role.
  - If an account qualifies both ways for the same role, the cell shows `"group"`.

A correct implementation must therefore resolve roles transitively across composite
roles and the group hierarchy — not just check the directly-listed names. (No special
cycle handling is required for the provided inputs.)

## Keycloak realm-export schema

The input is one JSON object describing a realm. Relevant fields (only the ones the
auditors read are listed; real exports contain many more, which must be ignored
gracefully):

**Top level / realm object**

- `realm` (str): realm name.
- `registrationAllowed`, `verifyEmail`, `bruteForceProtected` (bool).
- `revokeRefreshToken` (bool), `refreshTokenMaxReuse` (int).
- `accessTokenLifespan` (int seconds).
- `offlineSessionMaxLifespanEnabled` (bool).
- `keycloakVersion` (str).
- `passwordPolicy` (str, may be absent/empty): a Keycloak policy string such as
  `"length(12) and hashAlgorithm(pbkdf2-sha256) and hashIterations(27500)"`.
- `attributes` (object): misc realm attributes; `userProfileEnabled` (`"true"`/…) is
  read by the user-profile checks.
- `components` (object): provider components; the user-profile provider config lives
  under `components["org.keycloak.userprofile.UserProfileProvider"]`.
- `clients` (array, required), `clientScopes` (array, optional),
  `identityProviders` (array, optional), `identityProviderMappers` (array, required
  key — may be `[]`), `roles` (object with `realm` and `client` keys).
- `scopeMappings` (array, optional): top-level **realm-role** assignments made outside
  the client objects. Each entry is `{"client": <clientName>, "roles": [<realmRole>, …]}`
  **or** `{"clientScope": <scopeName>, "roles": […]}` and grants those realm roles to
  the named client (a *direct* role assignment) or to the named client scope.
- `clientScopeMappings` (object, optional): the same idea for **client** roles, keyed by
  the owning client's name → a list of `{"client"|"clientScope": <name>, "roles": […]}`
  entries granting that owner client's roles to the named client or client scope.

**Client object** (element of `clients`)

- `clientId` (str), `protocol` (`"openid-connect"` or `"saml"`), `enabled` (bool),
  `publicClient` (bool).
- Flow flags: `standardFlowEnabled`, `implicitFlowEnabled`,
  `directAccessGrantsEnabled`, `serviceAccountsEnabled` (bool).
- `fullScopeAllowed` (bool), `defaultClientScopes` / `optionalClientScopes` (arrays
  of scope names).
- `redirectUris` (array), `webOrigins` (array), `rootUrl` / `baseUrl` (optional str).
- `clientAuthenticatorType` (str, for confidential clients).
- `attributes` (object): includes `pkce.code.challenge.method`,
  `access.token.lifespan`, `use.refresh.tokens`, `post.logout.redirect.uris`
  (`##`-separated), the `oauth2.device.authorization.grant.enabled` flag, and the
  SAML attributes `saml.assertion.signature`, `saml.client.signature`,
  `saml.encrypt`, `saml.onetimeuse.condition`, `saml.signature.algorithm` (Keycloak
  serializes these booleans as the strings `"true"`/`"false"`; absent ⇒ treat as
  `false`/disabled, except `use.refresh.tokens` which defaults to `true`).

**Identity provider** (element of `identityProviders`)

- `alias` (str), `providerId` (`"oidc"`, `"keycloak-oidc"`, or `"saml"`), `enabled`
  (bool), `config` (object). `config` keys read: `syncMode` (default `"LEGACY"`),
  `pkceEnabled`, `pkceMethod`, `validateSignature`, `wantAssertionsEncrypted`,
  `wantAssertionsSigned`, `wantAuthnRequestsSigned`, `postBindingResponse` (all the
  booleans serialized as `"true"`/`"false"` strings).
- `identityProviderMappers` entries reference their IdP via `identityProviderAlias`.

**Client scope** (element of `clientScopes`)

- `name` (str), `protocolMappers` (array). Each protocol mapper has `protocolMapper`
  (type id, e.g. `"oidc-usermodel-attribute-mapper"`) and `config` (e.g.
  `config["user.attribute"]`).

**Roles, groups, service accounts** (used by the `review` subcommand)

- `roles.realm` (array): realm roles. Each has `name`, `clientRole: false`,
  `composite` (bool), and when composite a `composites` object of the shape
  `{"realm": [<role names>], "client": {<clientName>: [<role names>]}}` naming the
  roles this role includes.
- `roles.client` (object): maps each client name → array of that client's roles (same
  per-role shape, with `clientRole: true`).
- `groups` (array): each group has `name`, `path` (e.g. `/parent/child`), `realmRoles`
  (array of realm-role names granted to members), `clientRoles` (object
  clientName→[role names]), and `subGroups` (array of nested groups, recursively). A
  child group inherits all roles of its ancestors.
- `users` (array): in an export produced for `review`, these are the **service-account
  users**. Each has `username` (Keycloak names it `service-account-<clientId>`),
  `serviceAccountClientId` (the owning client's `clientId`), `realmRoles` (array),
  `clientRoles` (object), and `groups` (array of full group paths the account belongs
  to).

### Resolving redirect URIs

Several client auditors examine *resolved* redirect URIs: a redirect URI that starts
with `/` is resolved against the client's `rootUrl` (concatenated); otherwise it is
used as-is. Post-logout redirect URIs come from
`attributes["post.logout.redirect.uris"]`, split on `##`, with the inheritance marker
`"+"` skipped.

### The "users can freely edit their attributes" gate

The two user-attribute auditors
(`UsingNonDefaultUserAttributesInClientsWithoutUserProfilesFeatureIsDangerous` and
`UsingNonDefaultUserAttributesInScopesWithoutUserProfilesFeatureIsDangerous`) run only
when the realm enforces no user-profile policy on user attributes. Resolve this **once
per realm** from `attributes.userProfileEnabled` and the declarative user-profile config
stored in the `org.keycloak.userprofile.UserProfileProvider` component.

## Auditor catalog

Each auditor is a class; the class name is the value emitted as `reporting_auditor`
and is how `--auditors` selects it. Implement all of them — the broad-coverage tests
audit two full real-world realm exports and compare the **complete** set of
`(reporting_auditor, entity, entity_type, severity)` tuples, so any missing, extra,
or mis-severitied finding fails the comparison. Unless noted, client auditors skip
Keycloak's internal clients (`_system`, `admin-permissions`) and realm-specific
clients (the `master`-realm `*-realm` clients), and respect
`--ignore-disabled-clients`.

Severity is fixed per auditor unless stated. "Per redirect URI" means one finding is
emitted per offending URI.

### Realm auditors (`entity_type` = `Realm`)

- **PasswordPolicyMissing** — High. `passwordPolicy` is absent or empty.
- **PasswordHashingIterationsTooLow** — High. Password hashing iterations below the
  recommended minimum for the configured algorithm. Read algorithm + iteration count
  from the `passwordPolicy` string (`hashAlgorithm(...)`, `hashIterations(...)`),
  falling back to `passwordHashAlgorithm` / `passwordHashIterations`. Minimums:
  `pbkdf2-sha512` → 210000, `pbkdf2-sha256` → 600000, `pbkdf2` → 1300000. `argon2`
  and unknown algorithms / missing iteration counts are not flagged.
  `additional_details`: `algorithm` (str), `current_iterations` (int),
  `minimum_recommended_iterations` (int).
- **RealmBruteForceProtectionDisabled** — Info. `bruteForceProtected` is `false`.
- **RealmEmailVerificationDisabled** — Info. `verifyEmail` is `false`.
- **RealmSelfRegistrationEnabled** — Info. `registrationAllowed` is `true`.
- **OfflineSessionMaxLifespanDisabled** — Info. `offlineSessionMaxLifespanEnabled` is
  `false`.
- **RefreshTokensShouldBeRevokedAfterUse** — Medium. `revokeRefreshToken` is `false`.
- **RefreshTokenReuseCountShouldBeZero** — Medium. `revokeRefreshToken` is `true`
  **and** `refreshTokenMaxReuse` > 0.
- **AccessTokenLifespanTooLong** — High. `accessTokenLifespan` ≤ 0 (i.e. unlimited)
  or > 600 seconds. `additional_details`: `realm_access_token_lifespan` (int).
- **KeycloakVersionShouldBeUpToDate** — Medium (downgraded to **Low** if the version
  string contains `"redhat"`). Fires when the realm's `keycloakVersion` is not the
  latest upstream Keycloak release. The latest version is normally fetched from the
  GitHub releases API, **but the audit environment is offline**, so the lookup fails;
  in that case still emit the finding (any concrete version differs from an
  undeterminable "latest"). `additional_details`: `current_version` (str),
  `latest_version` (str; use a placeholder such as `"Could not be determined."` when
  the lookup fails).

### Client auditors (`entity_type` = `Client`)

Most apply only to OIDC clients (`protocol == "openid-connect"`); SAML-specific ones
require `protocol == "saml"`.

**Browser-redirect eligibility gate.** The redirect-URI checks below — namely
`ClientUsesCustomRedirectUriScheme`, `ClientHasUndefinedBaseDomainAndSchema`,
`ClientShouldNotUseWildcardRedirectURI`, `ClientMustNotUseGlobalWildcardURI`,
`ClientHasErroneouslyConfiguredWildcardURI`,
`ClientMustNotUseUnencryptedNonlocalRedirectUri`, and `ClientHasNoRedirectUris` —
only consider clients that can actually perform a browser redirect, i.e. with
`standardFlowEnabled` **or** `implicitFlowEnabled` set to `true`. Pure
service-account, device-flow-only, or direct-grant-only clients (both flow flags
`false`) are skipped by these checks. (The post-logout-redirect and web-origin checks
do **not** apply this gate.)

- **PublicClientsMustEnforcePKCE** — High. Public OIDC client with
  `standardFlowEnabled` and `attributes["pkce.code.challenge.method"] != "S256"`.
- **PublicClientShouldDisableDirectAccessGrants** — High. Public OIDC client with
  `directAccessGrantsEnabled` true.
- **ConfidentialClientShouldEnforcePKCE** — Medium. Confidential OIDC client with
  `standardFlowEnabled` and `pkce.code.challenge.method != "S256"` (excludes the
  built-in `broker` / `realm-management` clients).
- **ConfidentialClientShouldDisableDirectAccessGrants** — Medium. Confidential OIDC
  client with `directAccessGrantsEnabled` true.
- **ClientShouldDisableImplicitGrantFlow** — Medium. `implicitFlowEnabled` true.
- **ClientWithFullScopeAllowed** — Info. `fullScopeAllowed` true. `additional_details`
  include the default/optional scope lists.
- **ClientWithDefaultOfflineAccessScope** — Medium. `offline_access` in
  `defaultClientScopes`, the client allows user authentication (any of
  standard/implicit/direct-access/device flows), and refresh tokens are in use.
- **ClientWithOptionalOfflineAccessScope** — Medium. As above but for
  `optionalClientScopes`.
- **ClientWithServiceAccountAndOtherFlowEnabled** — Info. Confidential OIDC client
  with `serviceAccountsEnabled` true that *also* allows user authentication — i.e. any
  of `standardFlowEnabled`, `implicitFlowEnabled`, `directAccessGrantsEnabled`, or the
  device-authorization flow (`attributes["oauth2.device.authorization.grant.enabled"]`)
  is enabled.
- **ClientAuthenticationViaMTLSOrJWTRecommended** — Info. Confidential OIDC client
  (excluding `broker`/`realm-management`) whose `clientAuthenticatorType` is not one
  of the strong methods `federated-jwt`, `client-jwt`, `client-secret-jwt`,
  `client-x509`.
- **ClientAccessTokenLifespanTooLong** — High. OIDC client whose
  `attributes["access.token.lifespan"]` is set and ≤ 0 or > 600 seconds.
  `additional_details`: `client_access_token_lifespan` (int),
  `realm_access_token_lifespan` (int).
- **ClientHasNoRedirectUris** — Medium. Non-default OIDC client with standard or
  implicit flow enabled and an empty resolved redirect-URI list.
- **ClientUsesCustomRedirectUriScheme** — Info, per redirect URI. A resolved redirect
  URI whose scheme is not `http`, `https`, or empty (a custom app scheme).
  `additional_details`: `redirect_uri` (str).
- **ClientHasUndefinedBaseDomainAndSchema** — Info, per redirect URI. A resolved
  redirect URI with no scheme (relative). `additional_details`: `redirect_uri`.
- **ClientHasUndefinedBaseDomainAndSchemaInPostLogoutRedirectUri** — Info, per
  post-logout redirect URI with no scheme. `additional_details`:
  `post_logout_redirect_uri`.
- **ClientShouldNotUseWildcardRedirectURI** — Info, per redirect URI ending in `*`
  (the global `*` is excluded — that case is handled below).
  `additional_details`: `redirect_uri`, `public_client`.
- **ClientMustNotUseGlobalWildcardURI** — Critical, per redirect URI that is the
  global wildcard `*` (or `scheme://*`). `additional_details`: `redirect_uri`,
  `public_client`.
- **ClientHasErroneouslyConfiguredWildcardURI** — Critical, per redirect URI with a
  wildcard in the **domain** part (e.g. `https://host.example.com*`), excluding the
  global wildcard. `additional_details`: `redirect_uri`, `public_client`.
- **ClientMustNotUseUnencryptedNonlocalRedirectUri** — Medium, per redirect URI with
  scheme `http` to a non-local host (host not in `localhost`, `127.0.0.1`, `::1`).
  `additional_details`: `redirect_uri`.
- **ClientWebOriginsMustBeValid** — Info, per `webOrigins` entry that is neither the
  special `"+"`/`"*"` values nor a valid origin (scheme + host, no path/query).
- **ClientWebOriginsMustNotUseWildcard** — Medium. `"*"` present in `webOrigins`.
- **UsingNonDefaultUserAttributesInClientsWithoutUserProfilesFeatureIsDangerous** —
  High. When users can freely edit their attributes (no enforced user-profile
  policy), a client protocol mapper of type `oidc-usermodel-attribute-mapper` maps a
  `user.attribute` that is not one of Keycloak's built-in profile attributes (the
  exact allow-list is in **Key constants** below).

SAML clients (`protocol == "saml"`):

- **SamlClientWithAssertionSignatureDisabled** — High. `saml.assertion.signature` is
  not `"true"`.
- **SamlClientWithClientSignatureDisabled** — High. `saml.client.signature` is not
  `"true"`.
- **SamlClientWithEncryptionDisabled** — Medium. `saml.encrypt` is not `"true"`.
- **SamlClientWithoutOneTimeUseCondition** — Medium. `saml.onetimeuse.condition` is
  not `"true"`.
- **SamlClientWithWeakSignatureAlgorithm** — Medium. `saml.signature.algorithm` is a
  weak algorithm (`RSA_SHA1` or `DSA_SHA1`). `additional_details`:
  `detected_algorithm` (str).
- **SamlClientShouldNotUseWildcardRedirectURI** — Medium, per ACS/redirect URI ending
  in `*` (the global `*` is **not** excluded here). `additional_details`:
  `redirect_uri`.
- **SamlClientHasErroneouslyConfiguredWildcardURI** — Critical, per ACS/redirect URI
  with a wildcard in the domain part. `additional_details`: `redirect_uri`.

### Identity-provider auditors (`entity_type` = `IdentityProvider`)

- **OIDCIdentityProviderWithoutPKCE** — Medium. `providerId` in {`oidc`,
  `keycloak-oidc`} and PKCE not enabled with method `S256` (`config.pkceEnabled` !=
  `"true"` or `config.pkceMethod` != `"S256"`). `additional_details`: `pkceEnabled`,
  `pkceMethod` (with placeholder strings when unset).
- **IdentityProviderWithSignatureVerificationDisabled** — Critical. OIDC IdP with
  `config.validateSignature` != `"true"`.
- **SamlIdentityProviderWithSignatureVerificationDisabled** — Critical. SAML IdP
  (`providerId == "saml"`) with `config.validateSignature` != `"true"`.
- **SamlIdentityProviderWithoutSignedAssertions** — High. SAML IdP with
  `config.wantAssertionsSigned` != `"true"`.
- **SamlIdentityProviderWithoutEncryptedAssertions** — Medium. SAML IdP with
  `config.wantAssertionsEncrypted` != `"true"`.
- **SamlIdentityProviderWithoutSignedAuthnRequests** — Medium. SAML IdP with
  `config.wantAuthnRequestsSigned` != `"true"`.
- **SamlIdentityProviderWithoutPostBindingResponse** — Medium. SAML IdP with
  `config.postBindingResponse` != `"true"`.
- **IdentityProviderWithMappersWithoutForceSyncMode** — Medium. IdP whose `syncMode`
  is not `"FORCE"` and which has at least one identity-provider mapper referencing it.
- **IdentityProviderWithOneTimeSync** — Info. IdP whose `syncMode` is not `"FORCE"`
  (fires for every such IdP, independently of the mapper check above).

### Client-scope auditor (`entity_type` = `ClientScope`)

- **UsingNonDefaultUserAttributesInScopesWithoutUserProfilesFeatureIsDangerous** —
  High. When users can freely edit their attributes, a client-scope protocol mapper
  of type `oidc-usermodel-attribute-mapper` maps a `user.attribute` that is not a
  built-in Keycloak profile attribute (see **Key constants**). `additional_details`:
  `used-attribute` (str),
  `clients-using-scope` (list of client names that reference the scope).

## Monitor checks (config-driven)

Monitors are additional checks that run **only** when enabled through the `-c` YAML
config. They let an operator declare which roles / scopes / groups / protocol-mapper
configurations are "sensitive" and then report the realm objects that match. Like
auditors, each monitor is a class whose name is its `reporting_auditor` value and is
selectable with `--auditors <ClassName>`; their findings use the same JSON/CSV schema.
All monitors default to severity **Medium** unless an entry overrides it. Each monitor
reports each matching object **once** — a single object reached through several
resolution paths still yields one finding, not one per path.

### Config file format

The YAML config has two top-level keys, `auditors` and `monitors`, **each a list**
(both keys must be present, even if empty):

```yaml
auditors: []          # optional per-auditor allowlists: {auditor: <Class>, allowed: [...]}
monitors:
  - monitor: <MonitorClassName>
    config:
      - <entry>        # one or more entries; fields depend on the monitor (below)
      - ...
```

Every monitor entry supports these common fields: `allowed` (a list of names/paths
that are exempt — exact string, or a regex if it contains one of `? ! + *`),
`severity` (one of `Info`/`Low`/`Medium`/`High`/`Critical`, case-insensitive;
defaults to the monitor's Medium), and an optional `note`. Role-matching monitors take
`role` (name or regex) and `role-client` (a client name, or the literal `"realm"` for
realm roles). Name/scope/group matching uses the same exact-or-regex rule as `allowed`.

Roles are resolved **transitively**: a monitored role matches not only its direct
holders but anything reachable through composite roles (recursively), client-scope
assignments, and the group hierarchy — the same resolution described under the
`review` matrix.

### Monitors

- **ServiceAccountWithSensitiveRole** — entry keys `role`, `role-client`. Flags each
  service account (entity_type `ServiceAccount`) that holds the monitored role
  directly, via a (recursive) composite role, or via group membership.
  `additional_details.matched_by` is `"role"` or `"group"`.
- **ServiceAccountWithGroup** — entry keys `group` (path or regex), `allow_no_group`
  (bool). Flags service accounts that are in the monitored group, and (when
  `allow_no_group` is false) service accounts with no group at all.
- **ClientWithSensitiveRole** — entry keys `role`, `role-client`,
  `ignore_full_scope_allowed` (bool). Flags clients (entity_type `Client`) that obtain
  the monitored role through a direct role assignment
  (`matched_by` `"RoleAssignmentToClient"`) or through an assigned client scope
  (`matched_by` `"clientScope"`); when `ignore_full_scope_allowed` is false, also via
  `fullScopeAllowed` clients that have a role-mapper.
- **ClientWithSensitiveScope** — entry key `scope` (name or regex). Flags clients
  whose default or optional client scopes include the monitored scope.
- **GroupWithSensitiveRole** — entry keys `role`, `role-client`. Flags every group
  (entity_type `Group`) whose effective roles (own + inherited from ancestor groups,
  composite-expanded) include the monitored role. Two distinct groups may share a
  `name` (entity); both are reported.
- **RoleWithSensitiveAssociatedRole** — entry keys `role`, `role-client`. Flags every
  *other* role (entity_type `RealmRole` or `ClientRole`) whose composite transitively
  contains the monitored role.
- **ProtocolMapperWithConfig** — entry keys `protocol-mapper-type` (name or regex) and
  `matched-config` (a dict of config-key → value/regex; `{}` matches any mapper of the
  type). Flags clients carrying a matching protocol mapper (defined directly or via a
  client scope).
- **ProtocolMapperWithConfigOnClientScope** — same entry keys as above, but flags the
  matching **client scopes** themselves (entity_type `ClientScope`), regardless of
  whether any client uses them.

## Key constants

- Access-token lifespan threshold: 600 seconds (a lifespan of ≤ 0 means unlimited and
  is also flagged).
- PKCE expected method: `S256`.
- Weak SAML signature algorithms: `RSA_SHA1`, `DSA_SHA1`.
- Strong client authenticator types: `federated-jwt`, `client-jwt`,
  `client-secret-jwt`, `client-x509`.
- Local hosts (allowed for `http` redirects): `localhost`, `127.0.0.1`, `::1`.
- Built-in Keycloak profile attributes (a `user.attribute` equal to one of these does
  **not** trigger the user-attribute auditors): `firstName`, `nickname`, `zoneinfo`,
  `lastName`, `username`, `middleName`, `picture`, `birthdate`, `locale`, `website`,
  `gender`, `updatedAt`, `profile`, `phoneNumber`, `phoneNumberVerified`,
  `mobile_number`, `email`, `emailVerified`. Any other attribute name is "non-default"
  and triggers the check (when users can freely edit attributes).
- Built-in Keycloak clients excluded from "no redirect URIs": `account`,
  `account-console`, `admin-cli`, `broker`, `realm-management`,
  `security-admin-console`. Internal clients excluded from all client auditors:
  `_system`, `admin-permissions`.
