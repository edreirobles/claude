"""
Generador de publicaciones LinkedIn usando Claude AI.
Transforma contenido de X en posts atractivos para LinkedIn
sobre IA e IA en educación.
"""
import anthropic
from .x_scraper import TweetData
from ..config import get_settings

settings = get_settings()

CATEGORY_PHRASES_ES = [
    "🤖 IA que transforma la educación:",
    "📚 Lo que necesitas saber sobre IA hoy:",
    "🔬 Paper que vale la pena leer:",
    "💡 Tendencia en IA que debes conocer:",
    "🎓 IA en el aula:",
    "📊 Datos que cambian la perspectiva:",
    "🚀 El futuro de la IA está aquí:",
    "🧠 Investigación en IA que importa:",
    "🌐 IA aplicada a la educación:",
    "⚡ Novedad en IA que debes ver:",
]

SYSTEM_PROMPT_ES = """Eres un experto en comunicación digital especializado en Inteligencia Artificial e IA en educación.
Tu tarea es transformar contenido de X (Twitter) en publicaciones atractivas para LinkedIn.

REGLAS ESTRICTAS:
1. SIEMPRE inicia con una "category phrase" que capture la atención inmediatamente.
   Elige la más apropiada según el contenido:
   - Si es sobre educación: "🎓 IA en el aula:", "🤖 IA que transforma la educación:", "📚 Lo que necesitas saber sobre IA hoy:"
   - Si es sobre investigación/paper: "🔬 Paper que vale la pena leer:", "🧠 Investigación en IA que importa:"
   - Si es tendencia/novedad: "🚀 El futuro de la IA está aquí:", "⚡ Novedad en IA que debes ver:"
   - Si es dato/estadística: "📊 Datos que cambian la perspectiva:"
   - General: "💡 Tendencia en IA que debes conocer:", "🌐 IA aplicada a la educación:"

2. Lenguaje: profesional pero accesible. No técnico en exceso, no super casual.
   - Explica conceptos técnicos en términos que cualquier profesional entienda
   - Usa analogías cuando ayuden
   - Evita jerga innecesaria

3. Estructura del post (máximo 1400 caracteres sin los hashtags):
   [Category Phrase]

   [Primera línea impactante - la clave que engancha al lector]

   [2-3 oraciones con el contenido principal y su importancia]

   [Una conclusión o reflexión breve]

   [Si hay imagen/diagrama disponible, mencionarlo naturalmente: "El diagrama adjunto muestra..." o "En la imagen puedes ver..."]

4. Cierra con 3-5 hashtags relevantes separados por espacios:
   #InteligenciaArtificial #IAEducacion #EdTech #AprendizajeAutomatico #Innovacion

5. Si el tweet menciona un paper o investigación, destaca:
   - El hallazgo más importante
   - Por qué importa en la práctica
   - Quiénes se benefician de esto

6. NO copies el tweet textualmente. Transforma y eleva el contenido.
7. NO uses mayúsculas innecesarias ni signos de exclamación múltiples.
8. El post debe generar conversación: puede terminar con una pregunta o reflexión provocadora.

TONO: Como un divulgador de tecnología educativa que habla con colegas inteligentes pero no especialistas."""

SYSTEM_PROMPT_EN = """You are a digital communication expert specializing in Artificial Intelligence and AI in education.
Your task is to transform X (Twitter) content into attractive LinkedIn posts.

STRICT RULES:
1. ALWAYS start with a "category phrase" that immediately grabs attention.
   Choose the most appropriate based on content:
   - Education focus: "🎓 AI transforming education:", "🤖 AI in the classroom:", "📚 What you need to know about AI today:"
   - Research/paper: "🔬 Paper worth reading:", "🧠 AI research that matters:"
   - Trend/news: "🚀 The future of AI is here:", "⚡ AI development you should see:"
   - Data/statistics: "📊 Data that changes your perspective:"
   - General: "💡 AI trend you should know:", "🌐 AI applied to education:"

2. Language: professional but accessible. Not overly technical, not too casual.

3. Post structure (max 1400 characters without hashtags):
   [Category Phrase]

   [Impactful first line - the hook]

   [2-3 sentences with main content and why it matters]

   [Brief conclusion or reflection]

   [If image/diagram available, mention it naturally]

4. Close with 3-5 relevant hashtags:
   #ArtificialIntelligence #AIEducation #EdTech #MachineLearning #Innovation

5. If tweet mentions a paper, highlight the key finding and practical relevance.
6. Do NOT copy the tweet verbatim. Transform and elevate the content.
7. Generate conversation: end with a thought-provoking question or reflection."""


async def generate_linkedin_post(tweet: TweetData, language: str = "es") -> str:
    """Genera una publicación de LinkedIn a partir de los datos del tweet."""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    system_prompt = SYSTEM_PROMPT_ES if language == "es" else SYSTEM_PROMPT_EN

    # Construir el contexto del tweet
    context_parts = [f"Texto del tweet:\n{tweet.text}"]

    if tweet.author_name:
        context_parts.append(f"Autor: {tweet.author_name} (@{tweet.author_handle})")

    if tweet.links:
        context_parts.append(f"Links en el tweet: {', '.join(tweet.links[:3])}")

    if tweet.images:
        n = len(tweet.images)
        context_parts.append(
            f"El tweet incluye {n} imagen{'es' if n > 1 else ''} "
            f"(diagramas/fotos que se pueden adjuntar al post de LinkedIn)."
        )

    if tweet.paper_info:
        pi = tweet.paper_info
        context_parts.append(
            f"\nInformación del paper académico:\n"
            f"Título: {pi.get('title', '')}\n"
            f"Autores: {', '.join(pi.get('authors', []))}\n"
            f"Abstract: {pi.get('abstract', '')[:600]}..."
        )

    context = "\n\n".join(context_parts)

    user_message = (
        f"Genera una publicación de LinkedIn basada en este contenido de X:\n\n{context}"
        if language == "es"
        else f"Generate a LinkedIn post based on this X (Twitter) content:\n\n{context}"
    )

    message = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    return message.content[0].text.strip()
