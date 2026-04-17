import streamlit as st
from textwrap import dedent

st.set_page_config(
    page_title="Allocato",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="collapsed",
)

STRIPE_BASIC = "https://buy.stripe.com/fZu9AN2mIeJu3oRbNcfjG02"
STRIPE_PRO = "https://buy.stripe.com/3cIaERf9udFq2kN04ufjG01"
STRIPE_LIFETIME = "https://buy.stripe.com/8x2dR37H21WI4sV3gGfjG00"

def build_checkout_url(base_url: str) -> str:
    email = st.session_state.get("auth_user_email", "").strip().lower()
    if email:
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}locked_prefilled_email={email.replace("@", "%40")}"
    return base_url


if "lang" not in st.session_state:
    st.session_state.lang = "DE"

TEXT = {
    "DE": {
        "brand": "🚀 Allocato",
        "hero_title": "Dein smarter Portfolio-Manager für Direkttaktien.",
        "hero_subtitle": (
            "Mehr Kontrolle, mehr Transparenz, keine Black-Box. "
            "Allocato unterstützt dich dabei, Aktienportfolios intelligenter zu strukturieren — "
            "mit dynamischer Gewichtung statt blindem Buy & Hold und Dividenden direkt bei dir."
        ),
        "hero_badges": [
            "✨ Intelligente Dynamik",
            "📊 Klare Transparenz",
            "🛡️ Mehr Kontrolle",
            "💸 Dividenden direkt beim User",
        ],
        "hero_cta": "🚀 Jetzt kostenlos testen",
        "hero_note": "Starte direkt mit der echten Allocato-App.",
        "why_label": "WARUM ALLOCATO?",
        "why_title": "Mehr als Portfolio-Tracking — ein klares System für bessere Entscheidungen.",
        "why_text": (
            "Allocato ist für Anleger gemacht, die ihr Kapital bewusst steuern wollen. "
            "Statt intransparenten Produkten oder starren Standardlösungen bekommst du eine moderne, "
            "nachvollziehbare Oberfläche für direkte Aktienportfolios mit professionellem Anspruch."
        ),
        "features": [
            (
                "🎯",
                "Volle Kontrolle statt Produktlogik",
                "Du entscheidest selbst, welche Aktien in deinem Portfolio enthalten sind. "
                "Keine Black-Box-Produkte, keine fremde Struktur — sondern ein Setup, das zu deinem Ansatz passt.",
            ),
            (
                "🔍",
                "Maximale Transparenz",
                "Allocato macht Gewichtungen, Entwicklungen und Veränderungen klar sichtbar. "
                "Du erkennst jederzeit, wie dein Portfolio aufgebaut ist und warum es sich verändert.",
            ),
            (
                "⚡",
                "Dynamische Gewichtung statt blindem Buy & Hold",
                "Kapital wird nicht einfach statisch liegen gelassen. "
                "Allocato unterstützt einen intelligenteren Umgang mit Portfolio-Gewichten — modern, flexibel und logisch.",
            ),
            (
                "💰",
                "Direktes Eigentum bleibt bei dir",
                "Du investierst in Direkttaktien und behältst die volle Eigentümerschaft. "
                "Dividenden fließen direkt an dich — ohne Umwege über Fondsstrukturen oder intransparente Vehikel.",
            ),
        ],
        "how_label": "SO FUNKTIONIERT ALLOCATO",
        "how_title": "Ein klarer Weg von deinem Portfolio zur smarteren Struktur.",
        "how_text": (
            "Allocato macht Komplexität einfacher: von der Portfolio-Erstellung bis zur laufenden Steuerung — "
            "alles in einer intuitiven, professionellen Oberfläche."
        ),
        "steps": [
            (
                "1",
                "Portfolio anlegen",
                "Erstelle deinen eigenen Aktienkorb und starte mit genau den Titeln, die zu deinem Stil, Fokus und Marktverständnis passen.",
            ),
            (
                "2",
                "Struktur sichtbar machen",
                "Allocato zeigt dir übersichtlich, wie dein Portfolio aufgebaut ist und wo Chancen, Konzentrationen oder potenzielle Schwächen liegen.",
            ),
            (
                "3",
                "Gewichte intelligenter steuern",
                "Statt starrer Verteilungen setzt Allocato auf eine dynamische Logik, damit dein Kapital bewusster und moderner allokiert werden kann.",
            ),
            (
                "4",
                "Entwicklungen nachvollziehen",
                "Behalte Veränderungen, Schwerpunkte und Portfolio-Logik jederzeit im Blick — klar visualisiert und ohne unnötige Komplexität.",
            ),
            (
                "5",
                "Mit mehr Klarheit entscheiden",
                "Am Ende zählt ein besseres Gefühl für dein Portfolio: mehr Transparenz, mehr Kontrolle und ein deutlich professionelleres Gesamtbild.",
            ),
        ],
        "pricing_label": "PRICING",
        "pricing_title": "Vier Modelle. Ein Ziel: mehr Kontrolle über dein Portfolio.",
        "pricing_text": (
            "Starte kostenlos oder wähle den Plan, der zu deinem Anspruch passt. "
            "Alle Modelle sind klar strukturiert und auf echte Nutzung ausgelegt."
        ),
        "plans": [
            {
                "name": "Free",
                "price": "0 €",
                "period": "pro Monat",
                "features": ["1 Korb", "3 Jahre Historie", "Begrenzte Exports"],
                "button": "Kostenlos starten",
                "internal_page": "pages/1_Allocato.py",
                "badge": "",
                "highlight": False,
                "accent": "free",
                "button_kind": "secondary",
            },
            {
                "name": "Basic",
                "price": "19 €",
                "period": "pro Monat",
                "features": ["Unbegrenzte Körbe", "5 Jahre", "Alle CSV-Exports", "Globale Asset-Suche"],
                "button": "Basic wählen",
                "url": STRIPE_BASIC,
                "badge": "",
                "highlight": False,
                "accent": "basic",
                "button_kind": "secondary",
            },
            {
                "name": "Pro",
                "price": "39 €",
                "period": "pro Monat",
                "features": ["Alles aus Basic", "E-Mail-Alerts", "Gespeicherte Körbe", "Priorisierte Updates"],
                "button": "Pro starten",
                "url": STRIPE_PRO,
                "badge": "Beliebteste Wahl",
                "highlight": True,
                "accent": "pro",
                "button_kind": "primary",
            },
            {
                "name": "Lifetime",
                "price": "249 €",
                "period": "einmalig",
                "features": ["Alles für immer", "Alle Updates", "Limitiert auf erste 100 Käufer"],
                "button": "Lifetime sichern",
                "url": STRIPE_LIFETIME,
                "badge": "Limitiert",
                "highlight": False,
                "accent": "lifetime",
                "button_kind": "secondary",
            },
        ],
        "faq_label": "HÄUFIGE FRAGEN",
        "faq_title": "Die wichtigsten Antworten auf einen Blick.",
        "faq_text": "Alles, was potenzielle Nutzer vor dem Start mit Allocato wissen wollen.",
        "faq": [
            (
                "Was ist Allocato genau?",
                "Allocato ist ein smarter Portfolio-Manager für Direkttaktien. Die Plattform richtet sich an Anleger, die mehr Transparenz, mehr Kontrolle und eine moderne, nachvollziehbare Portfolio-Struktur wollen.",
            ),
            (
                "Für wen ist Allocato gedacht?",
                "Für Anleger, die ihr Portfolio nicht einfach nur laufen lassen möchten. Allocato ist ideal für Nutzer, die bewusst steuern, Strukturen verstehen und Entscheidungen mit mehr Klarheit treffen wollen.",
            ),
            (
                "Was unterscheidet Allocato von klassischem Buy & Hold?",
                "Allocato setzt auf eine intelligentere, dynamische Gewichtung statt auf starres Liegenlassen. Das Ziel ist nicht blinder Aktionismus, sondern ein modernerer Umgang mit Portfolio-Gewichten und eine bessere Übersicht über die eigene Kapitalallokation.",
            ),
            (
                "Bekomme ich bei Allocato weiterhin die Dividenden selbst?",
                "Ja. Der Fokus liegt auf Direkttaktien und damit auf direkter Eigentümerschaft. Dividenden bleiben beim Nutzer und fließen nicht in eine zwischengeschaltete Produktstruktur.",
            ),
            (
                "Kann ich Allocato kostenlos testen?",
                "Ja. Mit dem Free-Modell kannst du Allocato direkt ausprobieren und das Produktgefühl ohne Einstiegshürde kennenlernen.",
            ),
        ],
        "disclaimer_title": "Disclaimer:",
        "disclaimer_text": (
            "Allocato ist keine Anlageberatung und keine Aufforderung zum Kauf oder Verkauf von Wertpapieren. "
            "Alle Inhalte dienen ausschließlich Informations- und Marketingzwecken. Historische Ergebnisse, "
            "Simulationen oder Vergleiche sind keine Garantie für zukünftige Entwicklungen. "
            "Jede Anlageentscheidung erfolgt eigenverantwortlich."
        ),
        "bot_button": "🚀 Jetzt zum Allocato Bot gehen →",
    },
    "EN": {
        "brand": "🚀 Allocato",
        "hero_title": "Your Smart Portfolio Manager for Direct Stocks.",
        "hero_subtitle": (
            "More control, more transparency, no black box. "
            "Allocato helps you structure stock portfolios more intelligently — "
            "with dynamic weighting instead of blind buy & hold and dividends paid directly to you."
        ),
        "hero_badges": [
            "✨ Intelligent Dynamics",
            "📊 Clear Transparency",
            "🛡️ More Control",
            "💸 Dividends Paid Directly",
        ],
        "hero_cta": "🚀 Start for Free",
        "hero_note": "Launch directly into the live Allocato app.",
        "why_label": "WHY ALLOCATO?",
        "why_title": "More than portfolio tracking — a clear system for better decisions.",
        "why_text": (
            "Allocato is built for investors who want to manage their capital consciously. "
            "Instead of opaque products or rigid standard solutions, you get a modern, "
            "transparent interface for direct stock portfolios with a professional feel."
        ),
        "features": [
            (
                "🎯",
                "Full Control Instead of Product Logic",
                "You decide which stocks belong in your portfolio. No black-box products, no outside structure — just a setup that fits your own approach.",
            ),
            (
                "🔍",
                "Maximum Transparency",
                "Allocato makes weightings, developments, and changes clearly visible. You always understand how your portfolio is built and why it evolves.",
            ),
            (
                "⚡",
                "Dynamic Weighting Instead of Blind Buy & Hold",
                "Capital is not simply left sitting still. Allocato supports a smarter way to handle portfolio weights — modern, flexible, and logical.",
            ),
            (
                "💰",
                "Direct Ownership Stays with You",
                "You invest in direct stocks and keep full ownership. Dividends go straight to you — without detours through fund structures or opaque vehicles.",
            ),
        ],
        "how_label": "HOW ALLOCATO WORKS",
        "how_title": "A clear path from your portfolio to a smarter structure.",
        "how_text": (
            "Allocato simplifies complexity: from portfolio creation to ongoing management — "
            "all in one intuitive, professional interface."
        ),
        "steps": [
            (
                "1",
                "Create Your Portfolio",
                "Build your own basket of stocks and start with exactly the names that match your style, focus, and market view.",
            ),
            (
                "2",
                "Make Structure Visible",
                "Allocato shows clearly how your portfolio is built and where opportunities, concentrations, or potential weaknesses may exist.",
            ),
            (
                "3",
                "Manage Weights More Intelligently",
                "Instead of rigid allocations, Allocato uses dynamic logic so your capital can be positioned more consciously and more modernly.",
            ),
            (
                "4",
                "Track Developments Clearly",
                "Keep changes, focus areas, and portfolio logic in view at all times — clearly visualized and without unnecessary complexity.",
            ),
            (
                "5",
                "Decide with More Clarity",
                "In the end, it is about feeling better informed about your portfolio: more transparency, more control, and a more professional overall picture.",
            ),
        ],
        "pricing_label": "PRICING",
        "pricing_title": "Four plans. One goal: more control over your portfolio.",
        "pricing_text": "Start for free or choose the plan that matches your needs. All plans are clearly structured and designed for real use.",
        "plans": [
            {
                "name": "Free",
                "price": "0 €",
                "period": "per month",
                "features": ["1 basket", "3 years of history", "Limited exports"],
                "button": "Start for Free",
                "internal_page": "pages/1_Allocato.py",
                "badge": "",
                "highlight": False,
                "accent": "free",
                "button_kind": "secondary",
            },
            {
                "name": "Basic",
                "price": "19 €",
                "period": "per month",
                "features": ["Unlimited baskets", "5 years", "All CSV exports", "Global asset search"],
                "button": "Choose Basic",
                "url": STRIPE_BASIC,
                "badge": "",
                "highlight": False,
                "accent": "basic",
                "button_kind": "secondary",
            },
            {
                "name": "Pro",
                "price": "39 €",
                "period": "per month",
                "features": ["Everything in Basic", "Email alerts", "Saved baskets", "Prioritized updates"],
                "button": "Start Pro",
                "url": STRIPE_PRO,
                "badge": "Most Popular",
                "highlight": True,
                "accent": "pro",
                "button_kind": "primary",
            },
            {
                "name": "Lifetime",
                "price": "249 €",
                "period": "one-time",
                "features": ["Everything forever", "All updates", "Limited to first 100 buyers"],
                "button": "Secure Lifetime",
                "url": STRIPE_LIFETIME,
                "badge": "Limited",
                "highlight": False,
                "accent": "lifetime",
                "button_kind": "secondary",
            },
        ],
        "faq_label": "FAQ",
        "faq_title": "The most important answers at a glance.",
        "faq_text": "Everything potential users want to know before getting started with Allocato.",
        "faq": [
            (
                "What exactly is Allocato?",
                "Allocato is a smart portfolio manager for direct stocks. The platform is designed for investors who want more transparency, more control, and a modern, understandable portfolio structure.",
            ),
            (
                "Who is Allocato for?",
                "It is built for investors who do not want to simply let their portfolio run. Allocato is ideal for users who want to manage consciously, understand structure, and make decisions with greater clarity.",
            ),
            (
                "How is Allocato different from classic buy & hold?",
                "Allocato focuses on more intelligent, dynamic weighting instead of leaving allocations static. The goal is not blind activity, but a more modern way to manage portfolio weights and gain a better overview of capital allocation.",
            ),
            (
                "Do I still receive the dividends myself?",
                "Yes. The focus is on direct stock ownership, which means you keep direct ownership. Dividends stay with the user and do not flow through an intermediary product structure.",
            ),
            (
                "Can I try Allocato for free?",
                "Yes. With the Free plan, you can try Allocato immediately and experience the product without any entry barrier.",
            ),
        ],
        "disclaimer_title": "Disclaimer:",
        "disclaimer_text": (
            "Allocato is not investment advice and not a solicitation to buy or sell securities. "
            "All content is provided for informational and marketing purposes only. Historical results, "
            "simulations, or comparisons are not a guarantee of future performance. "
            "All investment decisions remain your own responsibility."
        ),
        "bot_button": "🚀 Go to the Allocato Bot now →",
    },
}

def section_header(label: str, title: str, text: str):
    st.markdown(f"<div class='section-label'>{label}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='section-title'>{title}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='section-text'>{text}</div>", unsafe_allow_html=True)

def render_feature_card(icon: str, title: str, text: str, cls: str):
    st.markdown(f"<div class='{cls}'>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"<div class='feature-icon'>{icon}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='feature-title'>{title}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='feature-text'>{text}</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

def render_step_card(num: str, title: str, text: str, cls: str):
    st.markdown(f"<div class='{cls}'>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"<div class='step-number'>{num}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='step-title'>{title}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='step-text'>{text}</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

def render_pricing_card(plan: dict, idx: int):
    accent = plan.get("accent", "free")
    wrapper_cls = f"pricing-wrapper pricing-{accent}"
    st.markdown(f"<div class='{wrapper_cls}'>", unsafe_allow_html=True)

    if plan["badge"]:
        badge_cls = "badge-popular" if plan["highlight"] else "badge-limited"
        st.markdown(
            f"<span class='pricing-badge {badge_cls}'>{plan['badge']}</span>",
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.markdown(f"<div class='plan-name'>{plan['name']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='plan-price'>{plan['price']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='plan-period'>{plan['period']}</div>", unsafe_allow_html=True)
        st.markdown("<div class='plan-divider'></div>", unsafe_allow_html=True)

        for feature in plan["features"]:
            st.markdown(f"<div class='plan-feature'>✓ {feature}</div>", unsafe_allow_html=True)

        st.markdown("<div class='plan-spacer'></div>", unsafe_allow_html=True)

        button_cls = "primary" if plan["button_kind"] == "primary" else "secondary"
        st.markdown(f"<div class='pricing-link {button_cls}'>", unsafe_allow_html=True)
        if plan.get("internal_page"):
            if st.button(plan["button"], key=f"plan_{idx}", use_container_width=True, type="primary" if plan["button_kind"] == "primary" else "secondary"):
                st.switch_page(plan["internal_page"])
        else:
            st.link_button(plan["button"], build_checkout_url(plan["url"]), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

t = TEXT[st.session_state.lang]

st.markdown(
    dedent(
        """
        <style>
            :root{
                --bg:#0f172a;
                --card:#1e2937;
                --card-soft:#243447;
                --text:#f8fafc;
                --muted:rgba(248,250,252,0.78);
                --line:rgba(255,255,255,0.08);
                --green:#22c55e;
                --green-dark:#16a34a;
                --green-soft:#86efac;
                --blue:#3b82f6;
                --blue-dark:#2563eb;
                --blue-soft:#93c5fd;
                --orange:#f59e0b;
                --orange-soft:#fcd34d;
                --shadow:0 18px 40px rgba(0,0,0,0.28);
                --shadow-hover:0 28px 60px rgba(0,0,0,0.38);
            }

            .stApp{
                background:
                    radial-gradient(circle at top left, rgba(34,197,94,0.08), transparent 22%),
                    radial-gradient(circle at top right, rgba(96,165,250,0.12), transparent 25%),
                    linear-gradient(180deg, #0f172a 0%, #111c31 100%);
                color:var(--text);
            }

            header[data-testid="stHeader"]{background:transparent;}
            [data-testid="stToolbar"]{right:1rem;}
            [data-testid="stDecoration"]{display:none;}

            .block-container{
                max-width:1220px;
                padding-top:1rem;
                padding-bottom:4rem;
            }

            div[data-testid="stRadio"] > div{
                justify-content:flex-end;
                gap:.25rem;
            }

            div[data-testid="stRadio"] label{
                color:#e2e8f0 !important;
                font-weight:700 !important;
            }

            .hero-wrap{
                border-radius:32px;
                padding:3.25rem 3rem 3rem 3rem;
                background:
                    radial-gradient(circle at 82% 18%, rgba(34,197,94,0.16), transparent 18%),
                    radial-gradient(circle at 12% 78%, rgba(96,165,250,0.14), transparent 22%),
                    linear-gradient(135deg, rgba(15,23,42,0.98) 0%, rgba(30,41,59,0.98) 100%);
                border:1px solid rgba(255,255,255,0.08);
                box-shadow:0 30px 90px rgba(0,0,0,0.38);
                margin-bottom:1.2rem;
                animation:fadeUp .55s ease both;
            }

            .brand-pill{
                display:inline-flex;
                align-items:center;
                gap:.6rem;
                padding:.48rem .88rem;
                border-radius:999px;
                background:rgba(255,255,255,0.05);
                border:1px solid rgba(255,255,255,0.08);
                margin-bottom:1.25rem;
                font-weight:700;
                color:#dbeafe;
            }

            .hero-title{
                font-size:clamp(3.35rem, 6vw, 6.15rem);
                line-height:.98;
                font-weight:900;
                letter-spacing:-.07em;
                margin:0 0 1rem 0;
                max-width:980px;
                text-wrap:balance;
            }

            .hero-subtitle{
                font-size:1.26rem;
                line-height:1.72;
                color:rgba(248,250,252,0.86);
                max-width:900px;
                margin-bottom:1.25rem;
            }

            .badge-row{
                display:flex;
                flex-wrap:wrap;
                gap:.7rem;
                margin-bottom:1rem;
            }

            .badge-pill{
                display:inline-flex;
                align-items:center;
                gap:.5rem;
                padding:.62rem .95rem;
                border-radius:999px;
                background:rgba(255,255,255,0.05);
                border:1px solid rgba(255,255,255,0.08);
                color:#e2e8f0;
                font-size:.95rem;
                font-weight:650;
                transition:all .3s ease;
            }

            .badge-pill:hover{
                transform:translateY(-4px) scale(1.05);
                box-shadow:0 24px 50px rgba(0,0,0,.30);
                background:rgba(255,255,255,0.08);
            }

            .section-label{
                color:#93c5fd;
                text-transform:uppercase;
                letter-spacing:.14em;
                font-size:.8rem;
                font-weight:800;
                margin-bottom:.75rem;
            }

            .section-title{
                font-size:clamp(2.35rem, 5vw, 4.25rem);
                line-height:1.06;
                font-weight:900;
                letter-spacing:-.055em;
                margin:0 0 .9rem 0;
                text-wrap:balance;
                max-width:980px;
            }

            .section-text{
                color:rgba(248,250,252,0.82);
                font-size:1.14rem;
                line-height:1.72;
                max-width:920px;
                margin-bottom:1.25rem;
            }

            .feature-icon{
                width:48px;
                height:48px;
                border-radius:14px;
                display:inline-flex;
                align-items:center;
                justify-content:center;
                font-size:1.35rem;
                margin-bottom:1rem;
                background:rgba(96,165,250,0.12);
                border:1px solid rgba(96,165,250,0.2);
            }

            .feature-title{
                font-size:1.46rem;
                font-weight:850;
                line-height:1.22;
                letter-spacing:-.03em;
                margin-bottom:.65rem;
                color:#f8fafc;
            }

            .feature-text{
                color:rgba(248,250,252,0.79);
                font-size:1.05rem;
                line-height:1.72;
            }

            .step-number{
                width:42px;
                height:42px;
                border-radius:999px;
                display:inline-flex;
                align-items:center;
                justify-content:center;
                font-size:.95rem;
                font-weight:800;
                color:#dbeafe;
                background:rgba(96,165,250,0.14);
                border:1px solid rgba(96,165,250,0.24);
                margin-bottom:.95rem;
            }

            .step-title{
                font-size:1.17rem;
                font-weight:850;
                line-height:1.28;
                margin-bottom:.55rem;
                letter-spacing:-.02em;
                color:#f8fafc;
            }

            .step-text{
                color:rgba(248,250,252,0.77);
                font-size:1rem;
                line-height:1.62;
            }

            .pricing-badge{
                display:inline-flex;
                align-items:center;
                justify-content:center;
                padding:.44rem .84rem;
                border-radius:999px;
                font-size:.78rem;
                font-weight:800;
                letter-spacing:.01em;
                margin-bottom:.7rem;
                transition:all .3s ease;
            }

            .badge-popular{
                background:linear-gradient(135deg, rgba(34,197,94,0.30), rgba(34,197,94,0.14));
                color:#ecfccb;
                border:1px solid rgba(34,197,94,0.46);
                box-shadow:0 10px 28px rgba(34,197,94,0.18);
            }

            .badge-limited{
                background:linear-gradient(135deg, rgba(96,165,250,0.22), rgba(59,130,246,0.10));
                color:#dbeafe;
                border:1px solid rgba(96,165,250,0.32);
                box-shadow:0 10px 28px rgba(59,130,246,0.16);
            }

            .plan-name{
                font-size:2rem;
                font-weight:850;
                letter-spacing:-.04em;
                margin-bottom:.25rem;
                color:#f8fafc;
            }

            .plan-price{
                font-size:3.35rem;
                line-height:.98;
                font-weight:900;
                letter-spacing:-.07em;
                margin-bottom:.25rem;
                color:#f8fafc;
            }

            .plan-period{
                color:rgba(248,250,252,0.68);
                font-size:1.02rem;
                margin-bottom:.95rem;
            }

            .plan-divider{
                height:1px;
                background:rgba(255,255,255,0.08);
                margin:.25rem 0 .95rem 0;
            }

            .plan-feature{
                color:rgba(248,250,252,0.88);
                font-size:1.06rem;
                line-height:1.62;
                margin-bottom:.72rem;
            }

            .plan-spacer{
                height:.9rem;
            }

            .faq-title{
                font-size:clamp(2.4rem, 5vw, 4.3rem);
                line-height:1.08;
                font-weight:900;
                letter-spacing:-.055em;
                margin-bottom:.9rem;
                text-wrap:balance;
                max-width:780px;
            }

            /* -------- Core cards -------- */
            [data-testid="stVerticalBlockBorderWrapper"]{
                border-radius:22px !important;
                border:1px solid rgba(255,255,255,0.08) !important;
                background:linear-gradient(180deg, rgba(30,41,59,0.98) 0%, rgba(25,36,53,0.98) 100%) !important;
                box-shadow:0 18px 40px rgba(0,0,0,0.28) !important;
                transition:all .32s ease !important;
                overflow:hidden !important;
            }

            [data-testid="stVerticalBlockBorderWrapper"]:hover{
                transform:translateY(-8px) scale(1.03);
                box-shadow:0 28px 60px rgba(0,0,0,0.38) !important;
                border-color:rgba(255,255,255,0.14) !important;
            }

            /* Prevent bottom clipping feeling */
            .feature-card-wrap [data-testid="stVerticalBlockBorderWrapper"],
            .step-card-wrap [data-testid="stVerticalBlockBorderWrapper"]{
                min-height:100%;
                padding-bottom:.15rem;
            }

            /* -------- Pricing wrappers -------- */
            .pricing-wrapper{
                animation:fadeUp .55s ease both;
            }

            .pricing-wrapper [data-testid="stVerticalBlockBorderWrapper"]{
                min-height:100%;
                padding-bottom:.1rem;
            }

            .pricing-free [data-testid="stVerticalBlockBorderWrapper"]{
                background:
                    radial-gradient(circle at top left, rgba(59,130,246,0.09), transparent 28%),
                    linear-gradient(180deg, rgba(19,32,57,0.98) 0%, rgba(18,30,52,0.98) 100%) !important;
            }

            .pricing-basic [data-testid="stVerticalBlockBorderWrapper"]{
                background:
                    radial-gradient(circle at top right, rgba(96,165,250,0.10), transparent 25%),
                    linear-gradient(180deg, rgba(22,35,61,0.98) 0%, rgba(20,34,57,0.98) 100%) !important;
                border-color:rgba(96,165,250,0.18) !important;
            }

            .pricing-basic [data-testid="stVerticalBlockBorderWrapper"]:hover{
                border-color:rgba(96,165,250,0.34) !important;
                box-shadow:
                    0 28px 60px rgba(0,0,0,0.38),
                    0 0 0 1px rgba(96,165,250,0.14) !important;
            }

            .pricing-pro [data-testid="stVerticalBlockBorderWrapper"]{
                background:
                    radial-gradient(circle at top right, rgba(34,197,94,0.22), transparent 28%),
                    radial-gradient(circle at bottom left, rgba(34,197,94,0.12), transparent 24%),
                    linear-gradient(180deg, rgba(23,44,39,0.98) 0%, rgba(21,38,37,0.98) 100%) !important;
                border:1px solid rgba(34,197,94,0.34) !important;
                box-shadow:
                    0 20px 44px rgba(0,0,0,0.30),
                    0 0 0 1px rgba(34,197,94,0.12) !important;
            }

            .pricing-pro [data-testid="stVerticalBlockBorderWrapper"]:hover{
                transform:translateY(-10px) scale(1.04);
                box-shadow:
                    0 30px 68px rgba(0,0,0,0.40),
                    0 0 0 1px rgba(34,197,94,0.18),
                    0 0 36px rgba(34,197,94,0.18) !important;
            }

            .pricing-lifetime [data-testid="stVerticalBlockBorderWrapper"]{
                background:
                    radial-gradient(circle at top right, rgba(96,165,250,0.14), transparent 26%),
                    linear-gradient(180deg, rgba(27,39,66,0.98) 0%, rgba(23,34,58,0.98) 100%) !important;
                border-color:rgba(96,165,250,0.22) !important;
            }

            .pricing-lifetime [data-testid="stVerticalBlockBorderWrapper"]:hover{
                border-color:rgba(96,165,250,0.34) !important;
                box-shadow:
                    0 28px 60px rgba(0,0,0,0.38),
                    0 0 0 1px rgba(96,165,250,0.12) !important;
            }

            /* -------- Buttons -------- */
            .hero-btn [data-testid="stLinkButton"] > a{
                min-height:58px;
                border-radius:16px;
                font-weight:800;
                background:linear-gradient(135deg, var(--green) 0%, var(--green-dark) 100%);
                color:white !important;
                border:1px solid rgba(255,255,255,0.10);
                box-shadow:0 16px 34px rgba(34,197,94,0.28);
                transition:all .32s ease;
            }

            .hero-btn [data-testid="stLinkButton"] > a:hover{
                transform:translateY(-6px) scale(1.05);
                box-shadow:
                    0 22px 46px rgba(34,197,94,0.34),
                    0 0 28px rgba(34,197,94,0.42);
                color:white !important;
            }

            .pricing-link [data-testid="stLinkButton"] > a{
                width:100%;
                min-height:58px;
                border-radius:16px;
                font-weight:800;
                color:white !important;
                border:1px solid rgba(255,255,255,0.10);
                transition:all .32s ease;
            }

            .pricing-link.secondary [data-testid="stLinkButton"] > a{
                background:linear-gradient(135deg, rgba(59,130,246,0.96) 0%, rgba(37,99,235,0.96) 100%);
                box-shadow:0 12px 26px rgba(59,130,246,0.24);
            }

            .pricing-link.primary [data-testid="stLinkButton"] > a{
                background:linear-gradient(135deg, var(--green) 0%, var(--green-dark) 100%);
                box-shadow:0 14px 30px rgba(34,197,94,0.30);
            }

            .pricing-link [data-testid="stLinkButton"] > a:hover{
                transform:translateY(-6px) scale(1.05);
                box-shadow:0 22px 42px rgba(0,0,0,0.30);
                color:white !important;
            }

            .pricing-link.primary [data-testid="stLinkButton"] > a:hover{
                box-shadow:
                    0 22px 46px rgba(34,197,94,0.34),
                    0 0 24px rgba(34,197,94,0.20);
            }

            /* -------- FAQ -------- */
            .stExpander{
                border:1px solid rgba(255,255,255,0.08) !important;
                border-radius:18px !important;
                background:linear-gradient(180deg, rgba(30,41,59,0.98) 0%, rgba(25,36,53,0.98) 100%) !important;
                box-shadow:0 18px 40px rgba(0,0,0,0.28);
                transition:all .3s ease;
                overflow:hidden;
                margin-bottom:.85rem;
            }

            .stExpander:hover{
                transform:translateY(-6px) scale(1.01);
                box-shadow:0 28px 60px rgba(0,0,0,0.38);
            }

            .stExpander summary{
                font-weight:800 !important;
                font-size:1.12rem !important;
                color:var(--text) !important;
            }

            @keyframes fadeUp{
                from{opacity:0; transform:translateY(18px);}
                to{opacity:1; transform:translateY(0);}
            }

            @media (max-width:900px){
                .hero-wrap{padding:2rem 1.25rem 1.7rem 1.25rem;}
                .hero-title{font-size:3rem;}
                .hero-subtitle{font-size:1.08rem;}
                .section-title,.faq-title{font-size:2.6rem;}
            }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

lang_left, lang_right = st.columns([8, 2], vertical_alignment="center")
with lang_right:
    new_lang = st.radio(
        "Language",
        ["DE", "EN"],
        index=0 if st.session_state.lang == "DE" else 1,
        horizontal=True,
        label_visibility="collapsed",
    )
    if new_lang != st.session_state.lang:
        st.session_state.lang = new_lang
        st.rerun()

t = TEXT[st.session_state.lang]

st.markdown(
    f"""
    <div class="hero-wrap">
        <div class="brand-pill">{t["brand"]}</div>
        <div class="hero-title">{t["hero_title"]}</div>
        <div class="hero-subtitle">{t["hero_subtitle"]}</div>
        <div class="badge-row">
            {''.join([f"<span class='badge-pill'>{badge}</span>" for badge in t["hero_badges"]])}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

hero_button_col, hero_note_col = st.columns([2, 5], vertical_alignment="center")
with hero_button_col:
    st.markdown('<div class="hero-btn">', unsafe_allow_html=True)
    if st.button(t["hero_cta"], type="primary", use_container_width=True):
        st.switch_page("pages/1_Allocato.py")
    st.markdown("</div>", unsafe_allow_html=True)
with hero_note_col:
    st.markdown(
        f"<div style='color:rgba(248,250,252,0.74);font-size:1rem;padding-top:.55rem;'>{t['hero_note']}</div>",
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
section_header(t["why_label"], t["why_title"], t["why_text"])

feature_cols_top = st.columns(2, gap="large")
for i, feature in enumerate(t["features"][:2]):
    with feature_cols_top[i]:
        render_feature_card(*feature, cls="feature-card-wrap")

feature_cols_bottom = st.columns(2, gap="large")
for i, feature in enumerate(t["features"][2:]):
    with feature_cols_bottom[i]:
        render_feature_card(*feature, cls="feature-card-wrap")

st.markdown("<div style='height:1.55rem'></div>", unsafe_allow_html=True)
section_header(t["how_label"], t["how_title"], t["how_text"])

step_cols = st.columns(5, gap="medium")
for i, step in enumerate(t["steps"]):
    with step_cols[i]:
        render_step_card(*step, cls="step-card-wrap")

st.markdown("<div style='height:1.55rem'></div>", unsafe_allow_html=True)
section_header(t["pricing_label"], t["pricing_title"], t["pricing_text"])

plan_cols = st.columns(4, gap="large")
for idx, plan in enumerate(t["plans"]):
    with plan_cols[idx]:
        render_pricing_card(plan, idx)

st.markdown("<div style='height:1.55rem'></div>", unsafe_allow_html=True)
st.markdown(f"<div class='section-label'>{t['faq_label']}</div>", unsafe_allow_html=True)
st.markdown(f"<div class='faq-title'>{t['faq_title']}</div>", unsafe_allow_html=True)
st.markdown(f"<div class='section-text'>{t['faq_text']}</div>", unsafe_allow_html=True)

for question, answer in t["faq"]:
    with st.expander(question):
        st.write(answer)

with st.container(border=True):
    st.markdown(f"**{t['disclaimer_title']}**")
    st.write(t["disclaimer_text"])

st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button(t["bot_button"], type="primary", use_container_width=True):
        st.switch_page("pages/1_Allocato.py")
