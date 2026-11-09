# Cosign Signing Key Rotation

**Rotation date:** 2026-11-09
**Reason:** Original private signing key became unavailable following a laptop migration.

## Previous signing identity

The historical public verification key is preserved at:

`docs/signing/cosign-legacy.pub`

SHA-256 of the public key file:
`d1b394d0e209f76e41b276ea6eb40426d876081e5982a0cdffaebb1a4bc5a6f8`

Loss of the private key does not itself establish compromise.
Historical signatures must be assessed under the appropriate trust policy.

## New signing identity

Active public verification key: `cosign.pub`

SHA-256 of the public key file:
`47335e6c6510ec23fef95d6ce4a165025dd23ea08967244c8bd1249d96d69b04`

A new password-protected Cosign key pair was generated.

Validation:
- Test blob signed successfully.
- Signature verified using the new public key.
- Sigstore transparency-log verification succeeded.
- Local encrypted backup created and recovery-tested.

## Operational notes

- Private signing keys must never be committed to Git.
- Jenkins uses Secret File and Secret Text credentials.
- An off-device encrypted backup is required for disaster recovery.
- Historical signatures should use the legacy public key.
- New signatures should use the active public key.
- Main-branch publishing, signing and attestation validation is pending.

## Future improvement

Move signing to a managed signing service such as AWS KMS
or use an appropriate workload-identity-based keyless signing solution.
