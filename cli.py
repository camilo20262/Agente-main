"""Interactive command-line interface for the shared AgentService."""

from agent import build_agent_service


def main() -> None:
    print("WPP Media Intelligence Agent. Escribe 'salir' para terminar.")
    service = build_agent_service()
    messages = []
    while True:
        try:
            question = input("\nPregunta: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in {"salir", "exit", "quit"}:
            break
        if question:
            messages.append({"role": "user", "content": question})
            result = service.run(messages)
            print("\n" + result.answer)
            messages.append({"role": "assistant", "content": result.answer})


if __name__ == "__main__":
    main()
