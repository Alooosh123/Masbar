import { AuthGate } from "./components/AuthGate";
import { ChatScreen } from "./components/ChatScreen";

export default function App() {
  return (
    <AuthGate>
      <ChatScreen />
    </AuthGate>
  );
}
