import crypto from 'crypto'
import bcrypt from 'bcryptjs'

// require_scoped_api_key (backend/v1/integrations/auth.py) verifies with
// bcrypt.checkpw against whatever hashing scheme produced api_key_hash —
// bcrypt hashes are self-describing, so hashing here with bcryptjs (Node)
// instead of Python's bcrypt is interoperable without any format coordination.
const BCRYPT_ROUNDS = 12

export function generateSandboxApiKey(): string {
  return `psb_${crypto.randomBytes(32).toString('base64url')}`
}

export async function hashSandboxApiKey(rawKey: string): Promise<string> {
  return bcrypt.hash(rawKey, BCRYPT_ROUNDS)
}
