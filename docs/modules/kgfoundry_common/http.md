# kgfoundry_common.http

HTTP client with retry strategy support.

[View source on GitHub](https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/http/__init__.py)

## Hierarchy

- **Parent:** [kgfoundry_common](../kgfoundry_common.md)
- **Children:** [kgfoundry_common.http.client](http/client.md), [kgfoundry_common.http.errors](http/errors.md), [kgfoundry_common.http.policy](http/policy.md), [kgfoundry_common.http.tenacity_retry](http/tenacity_retry.md), [kgfoundry_common.http.types](http/types.md)

## Sections

- **Public API**

## Contents

### kgfoundry_common.http.make_client_with_policy

::: kgfoundry_common.http.make_client_with_policy

## Relationships

**Imports:** `__future__.annotations`, `kgfoundry_common.http.client.HttpClient`, `kgfoundry_common.http.client.HttpSettings`, `kgfoundry_common.http.policy.PolicyRegistry`, `kgfoundry_common.http.tenacity_retry.TenacityRetryStrategy`, `pathlib.Path`

## Autorefs Examples

- [kgfoundry_common.http.make_client_with_policy][]

## Neighborhood

```d2
direction: right
"kgfoundry_common.http": "kgfoundry_common.http" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/http/__init__.py" }
"__future__.annotations": "__future__.annotations"
"kgfoundry_common.http" -> "__future__.annotations"
"kgfoundry_common.http.client.HttpClient": "kgfoundry_common.http.client.HttpClient"
"kgfoundry_common.http" -> "kgfoundry_common.http.client.HttpClient"
"kgfoundry_common.http.client.HttpSettings": "kgfoundry_common.http.client.HttpSettings"
"kgfoundry_common.http" -> "kgfoundry_common.http.client.HttpSettings"
"kgfoundry_common.http.policy.PolicyRegistry": "kgfoundry_common.http.policy.PolicyRegistry"
"kgfoundry_common.http" -> "kgfoundry_common.http.policy.PolicyRegistry"
"kgfoundry_common.http.tenacity_retry.TenacityRetryStrategy": "kgfoundry_common.http.tenacity_retry.TenacityRetryStrategy"
"kgfoundry_common.http" -> "kgfoundry_common.http.tenacity_retry.TenacityRetryStrategy"
"pathlib.Path": "pathlib.Path"
"kgfoundry_common.http" -> "pathlib.Path"
"kgfoundry_common": "kgfoundry_common" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/__init__.py" }
"kgfoundry_common" -> "kgfoundry_common.http" { style: dashed }
"kgfoundry_common.http.client": "kgfoundry_common.http.client" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/http/client.py" }
"kgfoundry_common.http" -> "kgfoundry_common.http.client" { style: dashed }
"kgfoundry_common.http.errors": "kgfoundry_common.http.errors" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/http/errors.py" }
"kgfoundry_common.http" -> "kgfoundry_common.http.errors" { style: dashed }
"kgfoundry_common.http.policy": "kgfoundry_common.http.policy" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/http/policy.py" }
"kgfoundry_common.http" -> "kgfoundry_common.http.policy" { style: dashed }
"kgfoundry_common.http.tenacity_retry": "kgfoundry_common.http.tenacity_retry" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/http/tenacity_retry.py" }
"kgfoundry_common.http" -> "kgfoundry_common.http.tenacity_retry" { style: dashed }
"kgfoundry_common.http.types": "kgfoundry_common.http.types" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/http/types.py" }
"kgfoundry_common.http" -> "kgfoundry_common.http.types" { style: dashed }
```

