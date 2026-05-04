"""Vérifie si le chat Claude est disponible : binaire `claude` + login OK."""
import asyncio
import shutil


async def check_claude_available() -> tuple[bool, str]:
    """Retourne (disponible, raison_si_KO).

    Vérifie en deux temps :
      1. Le binaire `claude` est dans le PATH.
      2. `claude --version` répond sans erreur (couvre le cas d'un binaire
         cassé). On NE teste pas le login ici : un login manquant ne
         fait échouer qu'au premier vrai message, et le drawer affichera
         un message d'erreur clair à ce moment-là.
    """
    if shutil.which("claude") is None:
        return False, (
            "binaire `claude` introuvable — installe Claude Code "
            "(npm install -g @anthropic-ai/claude-code) puis fais `claude login`"
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            return False, "le binaire `claude` ne répond pas (timeout 5s)"
    except Exception as e:
        return False, f"impossible de lancer `claude` : {e}"
    if proc.returncode != 0:
        return False, f"`claude --version` a renvoyé code {proc.returncode}"
    return True, ""
