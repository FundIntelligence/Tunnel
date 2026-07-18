export const ONTOLOGY_QA_EMAILS = [
  'mbakayaweever@gmail.com',
  'weevermbakaya@gmail.com',
  'weever@paritytunnel.com',
  'info@paritytunnel.com',
  'paritypm254@gmail.com',
  'samwelchegeh09@gmail.com',
]

export function isOntologyQaAllowed(email: string | null | undefined): boolean {
  if (!email) return false
  return ONTOLOGY_QA_EMAILS.includes(email.toLowerCase())
}
