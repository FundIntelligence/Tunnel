import { NextRequest, NextResponse } from 'next/server';
import { Resend } from 'resend';
import { createClient } from '@supabase/supabase-js';

const NOTIFY_EMAIL = 'mbakayaweever@gmail.com';

/**
 * POST /api/request-parser
 *
 * Accepts JSON (from the in-app modal) or multipart FormData (from /parsers/request page).
 *
 * JSON body:
 *   { bank_name, country, account_type, notes?, deal_id?, document_id?, original_filename?, contact_email?, partner? }
 *
 * FormData:
 *   bank_name, contact_email, notes?, sample_file? (File)
 *
 * partner: set by automatic callers (e.g. musa_file_processor.py passes
 * "musa") that already wrote their own row to the `parser_requests` table
 * directly. When set, this route sends the notification email only and
 * skips its own `pds_parser_requests` insert, so the same failure doesn't
 * show up twice in the admin dashboard (once "Auto · <partner>", once
 * "Manual").
 */
export async function POST(request: NextRequest) {
  const resend = new Resend(process.env.RESEND_API_KEY);
  try {
    const contentType = request.headers.get('content-type') ?? '';
    let bankName = '';
    let contactEmail = '';
    let notes = '';
    let country = '';
    let accountType = '';
    let dealId = '';
    let documentId = '';
    let originalFilename = '';
    let partner = '';
    let fileBuffer: ArrayBuffer | null = null;
    let fileName = '';
    let fileType = '';

    // ── Parse body ────────────────────────────────────────────────────────────
    if (contentType.includes('multipart/form-data')) {
      const form = await request.formData();
      bankName = (form.get('bank_name') as string) ?? '';
      contactEmail = (form.get('contact_email') as string) ?? '';
      notes = (form.get('notes') as string) ?? '';
      country = (form.get('country') as string) ?? '';
      accountType = (form.get('account_type') as string) ?? '';
      const sampleFile = form.get('sample_file') as File | null;
      if (sampleFile) {
        fileBuffer = await sampleFile.arrayBuffer();
        fileName = sampleFile.name;
        fileType = sampleFile.type || '';
      }
    } else {
      // JSON
      const body = (await request.json()) as Record<string, string>;
      bankName = body.bank_name ?? '';
      contactEmail = body.contact_email ?? '';
      notes = body.notes ?? '';
      country = body.country ?? '';
      accountType = body.account_type ?? '';
      dealId = body.deal_id ?? '';
      documentId = body.document_id ?? '';
      originalFilename = body.original_filename ?? '';
      partner = body.partner ?? '';
    }

    if (!bankName) {
      return NextResponse.json({ error: 'bank_name is required' }, { status: 400 });
    }

    // ── Build notification email HTML ─────────────────────────────────────────
    const partnerTag = partner ? ` [${partner.toUpperCase()}]` : '';
    const notifyHtml = `
      <h2 style="font-family:monospace;color:#14B8A6">🔧 Parser Request${partnerTag}: ${bankName}</h2>
      <table style="font-family:sans-serif;font-size:14px;border-collapse:collapse">
        ${partner ? `<tr><td style="padding:4px 12px 4px 0;color:#6b7280;font-weight:600">Partner</td><td>${partner}</td></tr>` : ''}
        <tr><td style="padding:4px 12px 4px 0;color:#6b7280;font-weight:600">Bank</td><td>${bankName}</td></tr>
        ${country ? `<tr><td style="padding:4px 12px 4px 0;color:#6b7280;font-weight:600">Country</td><td>${country}</td></tr>` : ''}
        ${accountType ? `<tr><td style="padding:4px 12px 4px 0;color:#6b7280;font-weight:600">Account type</td><td>${accountType}</td></tr>` : ''}
        ${contactEmail ? `<tr><td style="padding:4px 12px 4px 0;color:#6b7280;font-weight:600">Contact</td><td>${contactEmail}</td></tr>` : ''}
        ${dealId ? `<tr><td style="padding:4px 12px 4px 0;color:#6b7280;font-weight:600">Deal ID</td><td style="font-family:monospace">${dealId}</td></tr>` : ''}
        ${documentId ? `<tr><td style="padding:4px 12px 4px 0;color:#6b7280;font-weight:600">Document ID</td><td style="font-family:monospace">${documentId}</td></tr>` : ''}
        ${(originalFilename || fileName) ? `<tr><td style="padding:4px 12px 4px 0;color:#6b7280;font-weight:600">File</td><td style="font-family:monospace">${originalFilename || fileName}</td></tr>` : ''}
        ${notes ? `<tr><td style="padding:4px 12px 4px 0;color:#6b7280;font-weight:600;vertical-align:top">Notes</td><td>${notes}</td></tr>` : ''}
      </table>
      <hr style="margin:20px 0;border:none;border-top:1px solid #e5e7eb"/>
      <p style="font-family:monospace;font-size:12px;color:#9ca3af">
        Build parser following equity_extractor.py pattern.<br/>
        Deploy: <code>gcloud run deploy parity-ingestion --source .</code>
      </p>
    `;

    // ── Attachments (if file was uploaded) ────────────────────────────────────
    const attachments =
      fileBuffer && fileName
        ? [{ filename: fileName, content: Buffer.from(fileBuffer).toString('base64') }]
        : [];

    // ── Send notification to yourself ─────────────────────────────────────────
    const bankSlug = bankName.replace(/[^a-zA-Z0-9]/g, '_').slice(0, 40);
    await resend.emails.send({
      from: 'Parity Parser Requests <onboarding@resend.dev>',
      to: [NOTIFY_EMAIL],
      subject: `🔧 Parser Request${partnerTag}: ${bankName}`,
      html: notifyHtml,
      ...(attachments.length > 0 ? { attachments } : {}),
    });

    // ── Notify Slack (best-effort; never blocks or fails the request) ─────────
    //    Same firing point as the Resend email above. Reads SLACK_PARSER_WEBHOOK_URL
    //    (unset = no-op). The admin queue has no per-request route, so the link
    //    points at the queue list page, not a guessed per-request URL.
    const slackWebhook = process.env.SLACK_PARSER_WEBHOOK_URL;
    if (slackWebhook) {
      const adminBase = process.env.ADMIN_DASHBOARD_URL || 'https://parity-admin-three.vercel.app';
      const slackText = [
        `:wrench: *Parser Request${partnerTag}:* ${bankName}`,
        accountType ? `• Account type: ${accountType}` : '',
        country ? `• Country: ${country}` : '',
        contactEmail ? `• Contact: ${contactEmail}` : '',
        `• File: ${originalFilename || fileName || '—'}`,
        `• <${adminBase}/parser-requests|Open the parser-request queue>`,
      ].filter(Boolean).join('\n');
      try {
        await fetch(slackWebhook, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: slackText }),
        });
      } catch (slackErr) {
        console.error('[api/request-parser] slack notify failed:', slackErr);
      }
    }

    // ── Send confirmation to requester (if email provided) ────────────────────
    if (contactEmail) {
      await resend.emails.send({
        from: 'Parity <onboarding@resend.dev>',
        to: [contactEmail],
        subject: 'Bank Format Received — Parity',
        html: `
          <h2 style="font-family:monospace;color:#14B8A6">Bank Format Received</h2>
          <p style="font-family:sans-serif;font-size:14px">
            Thanks! We're onboarding the <strong>${bankName}</strong> format now.
          </p>
          <p style="font-family:sans-serif;font-size:14px">
            We'll email you at ${contactEmail} as soon as this format is ready so you can continue your analysis.
          </p>
          <hr style="margin:20px 0;border:none;border-top:1px solid #e5e7eb"/>
          <p style="font-family:sans-serif;font-size:12px;color:#9ca3af">Questions? Reply to this email.</p>
        `,
      });
    }

    // ── Log request to Supabase (skip when an auto/partner path already
    //    wrote its own parser_requests row — avoids a duplicate admin entry
    //    for the same failure) ───────────────────────────────────────────
    const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.STAGING_SUPABASE_SERVICE_ROLE_KEY;
    if (partner) {
      // Auto path (e.g. musa_file_processor.py) already inserted into
      // parser_requests directly; this call only needed the email above.
    } else if (!serviceRoleKey) {
      console.warn('[api/request-parser] No service role key — skipping DB insert');
    } else {
      const supabase = createClient(
        process.env.NEXT_PUBLIC_SUPABASE_URL!,
        serviceRoleKey
      );

      // Generate the row id up front so the stored object path and the DB row
      // are deterministically linked (bucket path = <requestId>/<filename>).
      const requestId = crypto.randomUUID();

      // ── Persist the uploaded sample file to Storage ───────────────────────
      // The Resend email above is no longer the only copy of the file. This is
      // best-effort: a Storage hiccup must not fail the request or lose the DB
      // row (the email attachment remains a fallback), so it is wrapped and
      // storage_path stays null on failure.
      let storagePath: string | null = null;
      if (fileBuffer && fileName) {
        const safeName = (originalFilename || fileName || 'file').replace(/[^a-zA-Z0-9._-]/g, '_');
        const objectPath = `${requestId}/${safeName}`;
        try {
          const { error: uploadError } = await supabase.storage
            .from('parser-requests')
            .upload(objectPath, Buffer.from(fileBuffer), {
              contentType: fileType || 'application/octet-stream',
              upsert: false,
            });
          if (uploadError) {
            console.error('[api/request-parser] storage upload failed:', uploadError.message);
          } else {
            storagePath = objectPath;
          }
        } catch (storageErr) {
          console.error('[api/request-parser] storage upload threw:', storageErr);
        }
      }

      await supabase.from('pds_parser_requests').insert({
        id: requestId,
        bank_name: bankName,
        country: country || null,
        account_type: accountType || null,
        notes: notes || null,
        deal_id: dealId || null,
        document_id: documentId || null,
        original_filename: originalFilename || fileName || null,
        storage_path: storagePath,
        status: 'new',
      });
    }

    return NextResponse.json({ success: true, bank_slug: bankSlug });
  } catch (error) {
    console.error('[api/request-parser] error:', error);
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Failed to submit parser request' },
      { status: 500 }
    );
  }
}
