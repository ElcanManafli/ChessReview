import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";

export const getRouter = () => {
  const queryClient = new QueryClient();

  const router = createRouter({
    routeTree,
    context: { queryClient },
    scrollRestoration: true,
    defaultPreloadStaleTime: 0,
  });

  return router;
};

import { useEffect } from "react";
import { supabase } from "./supabase";

function App() {
  useEffect(() => {
    async function checkConnection() {
      const { data, error } = await supabase.from("profiles").select("*").limit(1);
      if (error) {
        console.error("Supabase bağlantı xətası:", error.message);
      } else {
        console.log("Supabase uğurla bağlandı! Məlumat:", data);
      }
    }
    checkConnection();
  }, []);

  return (
    <div>
      <h1>Şahmat Layihəsi</h1>
    </div>
  );
}

export default App;
