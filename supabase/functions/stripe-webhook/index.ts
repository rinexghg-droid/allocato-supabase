import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import Stripe from "https://esm.sh/stripe@14.21.0";

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY")!, {
  apiVersion: "2023-10-16",
});

const endpointSecret = Deno.env.get("STRIPE_WEBHOOK_SECRET")!;

serve(async (req) => {
  const sig = req.headers.get("stripe-signature");

  let event;

  try {
    const body = await req.text();
    event = stripe.webhooks.constructEvent(body, sig!, endpointSecret);
  } catch (err) {
    return new Response(`Webhook Error: ${err.message}`, { status: 400 });
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object;

    const email = session.customer_details?.email;

    // 🔥 WICHTIG: Line items holen
    const lineItems = await stripe.checkout.sessions.listLineItems(session.id);

    const priceId = lineItems.data[0]?.price?.id;

    let tier = "Free";

    if (priceId === "price_1TMqIS8ndPVaUAm2NSUNqqhf") tier = "Pro";
    if (priceId === "price_1TMqHC8ndPVaUAm2s7zO7JFG") tier = "Basic";
    if (priceId === "price_1TMqJP8ndPVaUAm2anfhXmHT") tier = "Lifetime";

    await fetch(`${Deno.env.get("SUPABASE_URL")}/rest/v1/users?email=eq.${email}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "apikey": Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
        "Authorization": `Bearer ${Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")}`
      },
      body: JSON.stringify({
        subscription_tier: tier
      })
    });
  }

  return new Response("ok");
});