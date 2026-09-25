"""End-to-end tests for kcwarden — a Keycloak realm-configuration security auditor.

Each test drives the project through its CLI (`kcwarden audit ...`) on a Keycloak
realm-export JSON and asserts on the structured findings / exit code, exactly as a
real user or CI pipeline would.

`tests/fixtures/` holds two real Keycloak realm exports and the expected
normalized finding sets a correct implementation must produce on them.
"""

import csv
import io
import json
import os
import subprocess
from pathlib import Path

KCWARDEN = os.environ.get("KCWARDEN_BIN", "kcwarden")
FIXTURES = Path(__file__).parent / "fixtures"


def _run(*args, **kwargs):
    return subprocess.run([KCWARDEN, *args], capture_output=True, text=True, **kwargs)


def _audit(fixture, *args):
    return _run("audit", str(FIXTURES / fixture), *args)


def _normalize(findings):
    """Reduce a JSON finding list to a sorted list of the salient, stable fields."""
    return sorted(
        [f["reporting_auditor"], f["entity"], f["entity_type"], f["severity"]]
        for f in findings
    )


def _expected(name):
    return sorted(json.loads((FIXTURES / name).read_text()))


# --------------------------------------------------------------------------- #
# Full-audit snapshots (broad coverage on real realm exports)
# --------------------------------------------------------------------------- #
def test_full_audit_default_realm():
    """Running a full audit over a stock Keycloak realm export must produce exactly
    the expected set of findings (auditor, entity, entity type, severity)."""
    proc = _audit("default-realm.json", "--format", "json")
    assert proc.returncode == 0, proc.stderr
    assert _normalize(json.loads(proc.stdout)) == _expected("expected_default-realm.json")


def test_full_audit_test_realm_with_client():
    """A richer realm export (many misconfigured clients) must produce exactly the
    expected, larger finding set — exercising the bulk of the auditor suite and the
    Keycloak-export parsing at once."""
    proc = _audit("test-realm-with-client.json", "--format", "json")
    assert proc.returncode == 0, proc.stderr
    assert _normalize(json.loads(proc.stdout)) == _expected(
        "expected_test-realm-with-client.json"
    )


# --------------------------------------------------------------------------- #
# Finding schema + output formats
# --------------------------------------------------------------------------- #
def test_json_finding_schema():
    """Each JSON finding carries the full documented field set."""
    proc = _audit("default-realm.json", "--format", "json")
    findings = json.loads(proc.stdout)
    assert len(findings) > 0
    expected_keys = {
        "fingerprint",
        "severity",
        "realm",
        "entity",
        "entity_type",
        "reporting_auditor",
        "short_description",
        "long_description",
        "reference",
        "additional_details",
    }
    for f in findings:
        assert set(f.keys()) == expected_keys
        assert f["realm"] == "default-realm"


def test_csv_output_format():
    """`--format csv` emits a header row of all ten finding fields plus one row per
    finding."""
    proc = _audit("default-realm.json", "--format", "csv")
    assert proc.returncode == 0, proc.stderr
    rows = list(csv.DictReader(io.StringIO(proc.stdout)))
    assert set(rows[0].keys()) == {
        "fingerprint",
        "severity",
        "realm",
        "entity",
        "entity_type",
        "reporting_auditor",
        "short_description",
        "long_description",
        "reference",
        "additional_details",
    }
    assert len(rows) == 20  # default-realm yields 20 findings


# --------------------------------------------------------------------------- #
# CLI behaviour
# --------------------------------------------------------------------------- #
def test_min_severity_filter():
    """`--min-severity` filters out findings below the given CVSS-style severity."""
    all_findings = json.loads(_audit("default-realm.json", "--format", "json").stdout)
    assert len(all_findings) == 20  # Info 9 + Medium 8 + High 3

    medium = json.loads(
        _audit("default-realm.json", "--format", "json", "--min-severity", "MEDIUM").stdout
    )
    assert len(medium) == 11  # Medium 8 + High 3
    assert all(f["severity"] in {"Medium", "High", "Critical"} for f in medium)

    high = json.loads(
        _audit("default-realm.json", "--format", "json", "--min-severity", "HIGH").stdout
    )
    assert len(high) == 3
    assert all(f["severity"] in {"High", "Critical"} for f in high)


def test_fail_on_findings_exit_code():
    """`--fail-on-findings` exits 42 when findings exist; without it the exit code is
    0 even when findings are reported."""
    without = _audit("default-realm.json", "--format", "json")
    assert without.returncode == 0
    with_flag = _audit("default-realm.json", "--format", "json", "--fail-on-findings")
    assert with_flag.returncode == 42


def test_auditors_filter_runs_only_selected():
    """`--auditors <Name>` restricts the run to the named auditor(s); only that
    auditor's findings are produced."""
    proc = _audit(
        "default-realm.json", "--format", "json", "--auditors", "PasswordPolicyMissing"
    )
    findings = json.loads(proc.stdout)
    assert len(findings) == 1
    assert findings[0]["reporting_auditor"] == "PasswordPolicyMissing"
    assert findings[0]["entity_type"] == "Realm"
    assert findings[0]["entity"] == "default-realm"


# --------------------------------------------------------------------------- #
# Targeted single-auditor tests.
#
# Each runs one auditor in isolation (`--auditors <ClassName>`) over a small,
# purpose-built realm export and asserts the exact entities it flags (and, where
# stable, the structured `additional_details`). The fixtures contain a "clean"
# entity that must NOT be flagged plus the specific misconfigurations under test.
# --------------------------------------------------------------------------- #
def _findings(fixture, auditor, *extra):
    """Run a single auditor over a fixture and return its JSON findings."""
    proc = _audit(fixture, "--format", "json", "--auditors", auditor, *extra)
    assert proc.returncode == 0, proc.stderr
    findings = json.loads(proc.stdout)
    assert all(f["reporting_auditor"] == auditor for f in findings)
    return findings


def _flagged(fixture, auditor, *extra):
    """The set of entity names flagged by `auditor` on `fixture`."""
    return {f["entity"] for f in _findings(fixture, auditor, *extra)}


# ---- SAML client auditors (tests/fixtures/saml-realm.json) ---------------- #
def test_saml_assertion_signature_disabled():
    findings = _findings("saml-realm.json", "SamlClientWithAssertionSignatureDisabled")
    assert {f["entity"] for f in findings} == {"saml-no-sigs"}
    assert findings[0]["entity_type"] == "Client"
    assert findings[0]["severity"] == "High"


def test_saml_client_signature_disabled():
    findings = _findings("saml-realm.json", "SamlClientWithClientSignatureDisabled")
    assert {f["entity"] for f in findings} == {"saml-no-sigs"}
    assert findings[0]["severity"] == "High"


def test_saml_encryption_disabled():
    findings = _findings("saml-realm.json", "SamlClientWithEncryptionDisabled")
    assert {f["entity"] for f in findings} == {"saml-no-sigs"}
    assert findings[0]["severity"] == "Medium"


def test_saml_onetimeuse_condition_missing():
    findings = _findings("saml-realm.json", "SamlClientWithoutOneTimeUseCondition")
    assert {f["entity"] for f in findings} == {"saml-no-sigs"}
    assert findings[0]["severity"] == "Medium"


def test_saml_weak_signature_algorithm():
    findings = _findings("saml-realm.json", "SamlClientWithWeakSignatureAlgorithm")
    assert {f["entity"] for f in findings} == {"saml-weak-algo"}
    assert findings[0]["severity"] == "Medium"
    assert findings[0]["additional_details"]["detected_algorithm"] == "RSA_SHA1"


def test_saml_wildcard_redirect_uri():
    """Any ACS/redirect URI ending in `*` is flagged (global `*` not excluded)."""
    assert _flagged("saml-realm.json", "SamlClientShouldNotUseWildcardRedirectURI") == {
        "saml-wildcard-path",
        "saml-wildcard-domain",
    }


def test_saml_erroneous_wildcard_in_domain():
    """A wildcard in the domain part (e.g. `https://host*`) is Critical."""
    findings = _findings("saml-realm.json", "SamlClientHasErroneouslyConfiguredWildcardURI")
    assert {f["entity"] for f in findings} == {"saml-wildcard-domain"}
    assert findings[0]["severity"] == "Critical"


# ---- Identity-provider auditors (tests/fixtures/idp-realm.json) ----------- #
def test_oidc_idp_without_pkce():
    findings = _findings("idp-realm.json", "OIDCIdentityProviderWithoutPKCE")
    assert {f["entity"] for f in findings} == {"idp-oidc-nopkce"}
    assert findings[0]["entity_type"] == "IdentityProvider"
    assert findings[0]["severity"] == "Medium"


def test_oidc_idp_signature_verification_disabled():
    findings = _findings(
        "idp-realm.json", "IdentityProviderWithSignatureVerificationDisabled"
    )
    assert {f["entity"] for f in findings} == {"idp-oidc-nosig"}
    assert findings[0]["severity"] == "Critical"


def test_saml_idp_signature_verification_disabled():
    findings = _findings(
        "idp-realm.json", "SamlIdentityProviderWithSignatureVerificationDisabled"
    )
    assert {f["entity"] for f in findings} == {"idp-saml-insecure"}
    assert findings[0]["severity"] == "Critical"


def test_saml_idp_without_signed_assertions():
    findings = _findings("idp-realm.json", "SamlIdentityProviderWithoutSignedAssertions")
    assert {f["entity"] for f in findings} == {"idp-saml-insecure"}
    assert findings[0]["severity"] == "High"


def test_saml_idp_without_encrypted_assertions():
    findings = _findings(
        "idp-realm.json", "SamlIdentityProviderWithoutEncryptedAssertions"
    )
    assert {f["entity"] for f in findings} == {"idp-saml-insecure"}
    assert findings[0]["severity"] == "Medium"


def test_idp_mappers_without_force_sync_mode():
    findings = _findings(
        "idp-realm.json", "IdentityProviderWithMappersWithoutForceSyncMode"
    )
    assert {f["entity"] for f in findings} == {"idp-sync"}
    assert findings[0]["severity"] == "Medium"


def test_idp_one_time_sync():
    """Fires for every non-FORCE-sync IdP; only `idp-sync` is non-FORCE here."""
    findings = _findings("idp-realm.json", "IdentityProviderWithOneTimeSync")
    assert {f["entity"] for f in findings} == {"idp-sync"}
    assert findings[0]["severity"] == "Info"


# ---- Subtle OIDC client redirect/flow auditors (oidc-realm.json) ---------- #
def test_global_wildcard_redirect_uri():
    findings = _findings("oidc-realm.json", "ClientMustNotUseGlobalWildcardURI")
    assert {f["entity"] for f in findings} == {"global-wildcard"}
    assert findings[0]["severity"] == "Critical"


def test_custom_redirect_uri_scheme():
    findings = _findings("oidc-realm.json", "ClientUsesCustomRedirectUriScheme")
    assert {f["entity"] for f in findings} == {"custom-scheme"}
    assert findings[0]["severity"] == "Info"
    assert findings[0]["additional_details"]["redirect_uri"] == "myapp://callback"


def test_http_nonlocal_redirect_uri():
    findings = _findings(
        "oidc-realm.json", "ClientMustNotUseUnencryptedNonlocalRedirectUri"
    )
    assert {f["entity"] for f in findings} == {"http-nonlocal"}
    assert findings[0]["severity"] == "Medium"


def test_client_has_no_redirect_uris():
    findings = _findings("oidc-realm.json", "ClientHasNoRedirectUris")
    assert {f["entity"] for f in findings} == {"no-redirects"}
    assert findings[0]["severity"] == "Medium"


def test_client_access_token_lifespan_too_long():
    findings = _findings("oidc-realm.json", "ClientAccessTokenLifespanTooLong")
    assert {f["entity"] for f in findings} == {"long-token"}
    assert findings[0]["severity"] == "High"
    assert findings[0]["additional_details"]["client_access_token_lifespan"] == 3600


def test_client_should_disable_implicit_grant_flow():
    findings = _findings("oidc-realm.json", "ClientShouldDisableImplicitGrantFlow")
    assert {f["entity"] for f in findings} == {"implicit"}
    assert findings[0]["severity"] == "Medium"


def test_client_web_origins_wildcard():
    findings = _findings("oidc-realm.json", "ClientWebOriginsMustNotUseWildcard")
    assert {f["entity"] for f in findings} == {"weborigin-wildcard"}
    assert findings[0]["severity"] == "Medium"


def test_confidential_client_direct_access_grants():
    findings = _findings(
        "oidc-realm.json", "ConfidentialClientShouldDisableDirectAccessGrants"
    )
    assert {f["entity"] for f in findings} == {"confidential-dag"}
    assert findings[0]["severity"] == "Medium"


def test_client_with_default_offline_access_scope():
    findings = _findings("oidc-realm.json", "ClientWithDefaultOfflineAccessScope")
    assert {f["entity"] for f in findings} == {"default-offline"}
    assert findings[0]["severity"] == "Medium"


# ---- Realm-level + scope auditors (settings-realm.json) ------------------- #
def test_realm_self_registration_enabled():
    findings = _findings("settings-realm.json", "RealmSelfRegistrationEnabled")
    assert {f["entity"] for f in findings} == {"settings-realm"}
    assert findings[0]["entity_type"] == "Realm"
    assert findings[0]["severity"] == "Info"


def test_refresh_token_reuse_count_should_be_zero():
    findings = _findings("settings-realm.json", "RefreshTokenReuseCountShouldBeZero")
    assert {f["entity"] for f in findings} == {"settings-realm"}
    assert findings[0]["severity"] == "Medium"


def test_realm_access_token_lifespan_too_long():
    findings = _findings("settings-realm.json", "AccessTokenLifespanTooLong")
    assert {f["entity"] for f in findings} == {"settings-realm"}
    assert findings[0]["severity"] == "High"
    assert findings[0]["additional_details"]["realm_access_token_lifespan"] == 3600


def test_password_hashing_iterations_too_low():
    findings = _findings("settings-realm.json", "PasswordHashingIterationsTooLow")
    assert {f["entity"] for f in findings} == {"settings-realm"}
    assert findings[0]["severity"] == "High"
    details = findings[0]["additional_details"]
    assert details["algorithm"] == "pbkdf2-sha256"
    assert details["current_iterations"] == 1000


def test_scope_with_nondefault_user_attribute():
    findings = _findings(
        "settings-realm.json",
        "UsingNonDefaultUserAttributesInScopesWithoutUserProfilesFeatureIsDangerous",
    )
    assert {f["entity"] for f in findings} == {"custom-scope"}
    assert findings[0]["entity_type"] == "ClientScope"
    assert findings[0]["severity"] == "High"
    assert findings[0]["additional_details"]["used-attribute"] == "ssn"


# --------------------------------------------------------------------------- #
# `review` subcommand — service-account ⇄ sensitive-role resolution matrix.
#
# `kcwarden review <export>` emits a CSV matrix: one column per service-account
# username (plus a leading "role" column) and one row per realm/client role. A cell
# holds how that service account obtains that role — "role" (directly assigned, or via
# a composite role that transitively contains it) or "group" (granted through group
# membership, including parent-group inheritance) — or is empty. This exercises the
# recursive composite-role expansion and the group hierarchy, the hardest part of the
# object model. The fixture `test-realm-with-client.json` is purpose-built with one
# service account per resolution path.
# --------------------------------------------------------------------------- #
SA = "service-account-client-with-service-account-"


def _review(fixture):
    """Run `review` and return {role_label: {service_account: matched_by}} (populated
    cells only)."""
    proc = _run("review", str(FIXTURES / fixture))
    assert proc.returncode == 0, proc.stderr
    matrix = {}
    for row in csv.DictReader(io.StringIO(proc.stdout)):
        role = row.pop("role")
        matrix[role] = {sa: how for sa, how in row.items() if how}
    return matrix


def test_review_matrix_structure():
    """The matrix has a leading `role` column plus exactly one column per service
    account in the realm."""
    proc = _run("review", str(FIXTURES / "test-realm-with-client.json"))
    assert proc.returncode == 0, proc.stderr
    header = next(csv.reader(io.StringIO(proc.stdout)))
    assert header[0] == "role"
    expected_service_accounts = {
        SA + "in-recursive-sensitive-group",
        SA + "in-sensitive-group",
        SA + "with-benign-role",
        SA + "in-subgroup-of-sensitive-composite-group",
        SA + "with-recursive-sensitive-role",
        SA + "with-sensitive-composite-role",
        SA + "with-sensitive-role",
        "service-account-service-account-client-with-client-role",
        "service-account-service-account-client-with-service-account-in-sensitive-subgroup",
    }
    assert set(header[1:]) == expected_service_accounts


def test_review_sensitive_realm_role_full_resolution():
    """Every way a service account can hold the sensitive realm role must be detected:
    direct assignment, a composite role, a recursive (2-level) composite role, direct
    group membership, a group holding the role via a composite, and a subgroup
    inheriting the role from its parent."""
    matrix = _review("test-realm-with-client.json")
    assert matrix["realm.sensitive-role"] == {
        # directly assigned, or via (recursive) composite role
        SA + "with-sensitive-role": "role",
        SA + "with-sensitive-composite-role": "role",
        SA + "with-recursive-sensitive-role": "role",
        # granted through group membership (incl. composite-on-group and subgroup
        # inheritance)
        SA + "in-sensitive-group": "group",
        SA + "in-recursive-sensitive-group": "group",
        SA + "in-subgroup-of-sensitive-composite-group": "group",
        "service-account-service-account-client-with-service-account-in-sensitive-subgroup": "group",
    }


def test_review_recursive_composite_role_resolution():
    """The intermediate composite role is itself resolved only through the recursive
    composite chain / groups — not by direct assignment to most accounts."""
    matrix = _review("test-realm-with-client.json")
    assert matrix["realm.recursive_sensitive_composite_role"] == {
        SA + "with-recursive-sensitive-role": "role",
        SA + "in-recursive-sensitive-group": "group",
        SA + "in-subgroup-of-sensitive-composite-group": "group",
    }


def test_review_client_role_direct_assignment():
    """Client-scoped roles are resolved and labelled `<client>.<role>`; a directly
    assigned client role shows as a `role` match for exactly its holder."""
    matrix = _review("test-realm-with-client.json")
    assert matrix["client-with-client-roles.sensitive-client-role"] == {
        "service-account-service-account-client-with-client-role": "role",
    }


# --------------------------------------------------------------------------- #
# Config-driven "monitor" checks (`audit -c <config.yaml>`).
#
# Monitors are extra checks the `audit` subcommand runs only when enabled by a YAML
# config file (`-c`). Each names sensitive roles / scopes / groups / protocol-mapper
# configs to watch for, with regex support and per-entry allowlists, and reports the
# realm objects that match — resolving roles transitively across composite roles, the
# group hierarchy, and client-scope assignments. `tests/fixtures/monitor-config.yaml`
# enables one entry per monitor against the sensitive objects in
# `test-realm-with-client.json`. Monitors are selected by class name like auditors.
# --------------------------------------------------------------------------- #
CONFIG = str(FIXTURES / "monitor-config.yaml")


def _monitor(monitor, fixture="test-realm-with-client.json"):
    proc = _audit(fixture, "-c", CONFIG, "--auditors", monitor, "--format", "json")
    assert proc.returncode == 0, proc.stderr
    findings = json.loads(proc.stdout)
    assert all(f["reporting_auditor"] == monitor for f in findings)
    return findings


def test_monitor_service_account_with_sensitive_role():
    """The sensitive realm role is resolved to every holding service account (direct,
    composite, recursive, and via groups); the finding takes the config's severity."""
    findings = _monitor("ServiceAccountWithSensitiveRole")
    assert {f["entity"] for f in findings} == {
        SA + "with-sensitive-role",
        SA + "with-sensitive-composite-role",
        SA + "with-recursive-sensitive-role",
        SA + "in-sensitive-group",
        SA + "in-recursive-sensitive-group",
        SA + "in-subgroup-of-sensitive-composite-group",
        "service-account-service-account-client-with-service-account-in-sensitive-subgroup",
    }
    assert len(findings) == 7  # exactly one finding per matching object (no duplicates)
    assert all(f["entity_type"] == "ServiceAccount" for f in findings)
    assert all(f["severity"] == "High" for f in findings)  # config overrides default
    assert {f["additional_details"]["matched_by"] for f in findings} == {"role", "group"}


def test_monitor_client_with_sensitive_role():
    """Clients are flagged for a sensitive role assigned directly or carried by a
    client scope (composite/recursive roles included)."""
    findings = _monitor("ClientWithSensitiveRole")
    assert {f["entity"] for f in findings} == {
        "client-with-explicitly-defined-roles-in-client-scope",
        "client-with-recursive-sensitive-composite-role",
        "client-with-scope-containing-client-role-with-sensitive-realm-role",
        "client-with-sensitive-composite-role",
        "client-with-sensitive-role",
    }
    assert len(findings) == 5  # exactly one finding per matching client (no duplicates)
    assert all(f["entity_type"] == "Client" for f in findings)
    by_entity = {f["entity"]: f["additional_details"]["matched_by"] for f in findings}
    assert by_entity["client-with-explicitly-defined-roles-in-client-scope"] == "RoleAssignmentToClient"
    assert by_entity["client-with-sensitive-role"] == "clientScope"


def test_monitor_client_with_sensitive_scope():
    findings = _monitor("ClientWithSensitiveScope")
    assert len(findings) == 1
    assert {f["entity"] for f in findings} == {"client-with-sensitive-role"}
    assert findings[0]["entity_type"] == "Client"


def test_monitor_group_with_sensitive_role():
    """Every group whose effective roles (own + inherited from parent groups, with
    composite expansion) include the sensitive role is flagged (each matching group
    is reported)."""
    findings = _monitor("GroupWithSensitiveRole")
    assert sorted({f["entity"] for f in findings}) == [
        "composite-sensitive-child-group",
        "group-with-sensitive-child-group",
        "recursive-sensitive-composite-group",
        "sensitive-child-group",
        "sensitive-group",
        "subgroup-of-recursive-sensitive-composite-group",
    ]
    assert all(f["entity_type"] == "Group" for f in findings)


def test_monitor_role_with_sensitive_associated_role():
    """Roles whose composite (transitively) contains the sensitive role are flagged;
    both realm and client container roles are reported with their object type."""
    findings = _monitor("RoleWithSensitiveAssociatedRole")
    assert len(findings) == 3  # no duplicate findings per container role
    by_entity = {f["entity"]: f["entity_type"] for f in findings}
    assert by_entity == {
        "sensitive_composite_role": "RealmRole",
        "recursive_sensitive_composite_role": "RealmRole",
        "client-role-containing-sensitive-realm-role": "ClientRole",
    }


def test_monitor_service_account_with_group():
    findings = _monitor("ServiceAccountWithGroup")
    assert len(findings) == 1
    assert {f["entity"] for f in findings} == {
        "service-account-client-with-service-account-in-sensitive-group"
    }
    assert findings[0]["entity_type"] == "ServiceAccount"


def test_monitor_protocol_mapper_on_client_scope():
    """Client scopes carrying a protocol mapper of the watched type are flagged
    (matched by mapper type, empty `matched-config` matching any such mapper)."""
    findings = _monitor("ProtocolMapperWithConfigOnClientScope")
    assert len(findings) == 2
    assert {f["entity"] for f in findings} == {"microprofile-jwt", "roles"}
    assert all(f["entity_type"] == "ClientScope" for f in findings)
