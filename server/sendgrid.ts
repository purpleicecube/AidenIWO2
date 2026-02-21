// SendGrid integration via Replit Connectors
import sgMail from '@sendgrid/mail';

let connectionSettings: any;

async function getCredentials() {
  const hostname = process.env.REPLIT_CONNECTORS_HOSTNAME;
  const xReplitToken = process.env.REPL_IDENTITY
    ? 'repl ' + process.env.REPL_IDENTITY
    : process.env.WEB_REPL_RENEWAL
    ? 'depl ' + process.env.WEB_REPL_RENEWAL
    : null;

  if (!xReplitToken) {
    throw new Error('X_REPLIT_TOKEN not found for repl/depl');
  }

  connectionSettings = await fetch(
    'https://' + hostname + '/api/v2/connection?include_secrets=true&connector_names=sendgrid',
    {
      headers: {
        'Accept': 'application/json',
        'X_REPLIT_TOKEN': xReplitToken
      }
    }
  ).then(res => res.json()).then(data => data.items?.[0]);

  if (!connectionSettings || (!connectionSettings.settings.api_key || !connectionSettings.settings.from_email)) {
    throw new Error('SendGrid not connected');
  }
  return { apiKey: connectionSettings.settings.api_key, email: connectionSettings.settings.from_email };
}

async function getUncachableSendGridClient() {
  const { apiKey, email } = await getCredentials();
  sgMail.setApiKey(apiKey);
  return {
    client: sgMail,
    fromEmail: email
  };
}

export async function sendInviteEmail(toEmail: string, inviterName: string, appUrl: string): Promise<void> {
  const { client, fromEmail } = await getUncachableSendGridClient();

  const msg = {
    to: toEmail,
    from: fromEmail,
    subject: `You've been invited to AIDEN_IWO`,
    text: `${inviterName} has invited you to join AIDEN_IWO — an intelligent work order orchestration platform.\n\nClick the link below to get started:\n${appUrl}\n\nOnce you sign in, an administrator will assign your role.`,
    html: `
      <div style="font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px;">
        <h2 style="color: #111827; margin-bottom: 8px;">You're invited to AIDEN_IWO</h2>
        <p style="color: #4b5563; font-size: 15px; line-height: 1.6;">
          <strong>${inviterName}</strong> has invited you to join <strong>AIDEN_IWO</strong> — an intelligent work order orchestration platform.
        </p>
        <a href="${appUrl}" style="display: inline-block; margin: 24px 0; padding: 12px 28px; background-color: #2563eb; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: 500; font-size: 15px;">
          Get Started
        </a>
        <p style="color: #6b7280; font-size: 13px; line-height: 1.5;">
          Once you sign in, an administrator will assign your role.
        </p>
      </div>
    `
  };

  await client.send(msg);
}
