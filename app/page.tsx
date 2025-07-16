"use client";
import { useState, useRef, useEffect } from "react"
import { Send, Calendar, MapPin, ArrowLeft, Search, Bot, CalendarDays, User, Sparkles } from "lucide-react"
import { motion, AnimatePresence } from "framer-motion"

interface Event {
  airtable_id: string
  name: string
  linked_space?: string
  start_time?: string
  end_time?: string
  owner?: string
  notes?: string
  programme?: string
  workstream?: string
}

interface Message {
  type: "user" | "bot"
  content: string
  timestamp: Date
  showInput?: boolean
  placeholder?: string
  showYesNo?: boolean
  showBackToHome?: boolean
  eventOptions?: Event[]
}

export default function EventsChatbot() {
  const [messages, setMessages] = useState<Message[]>([])
  const [eventList, setEventList] = useState<Event[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [currentFlow, setCurrentFlow] = useState("home")
  const [showChat, setShowChat] = useState(false)
  const [input, setInput] = useState("")
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const API_URL = "";

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, isLoading])

  const addMessage = (type: "user" | "bot", content: string, options: Partial<Message> = {}) => {
    setMessages((prev) => [...prev, { type, content, timestamp: new Date(), ...options }])
  }

  const handleCategorySelect = (category: "Events" | "Location" | "Date") => {
    setShowChat(true)
    setMessages([])
    setEventList([])
    addMessage("user", `I want to explore by ${category}`)

    let prompt: string, flow: string
    if (category === "Events") {
      prompt = "Perfect! What event are you looking for?"
      flow = "events"
    } else if (category === "Location") {
      prompt = "Great! Enter the location to see its schedule."
      flow = "location"
    } else {
      prompt = "Understood! Please enter the date (e.g., YYYY-MM-DD)."
      flow = "date-events"
    }

    setCurrentFlow(flow)
    addMessage("bot", prompt, { showInput: true, placeholder: `e.g., Opening Ceremony...` })
  }

  const formatDate = (dateString?: string) => {
    if (!dateString) return { date: "N/A", time: "" }
    const dt = new Date(dateString)
    return {
      date: dt.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" }),
      time: dt.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true, timeZone: "UTC" }),
    }
  }

  const formatEventDetails = (event: Event) => {
    const { date, time: startTime } = formatDate(event.start_time)
    const { time: endTime } = formatDate(event.end_time)
    let details = `📌 **${event.name || "Unnamed Event"}**\n`
    details += `📅 ${date}\n`
    details += `⏰ ${startTime} – ${endTime}\n`
    if (event.linked_space) details += `📍 **Locations:** ${event.linked_space}\n`
    if (event.programme) details += `🧭 **Programme:** ${event.programme}\n`
    if (event.workstream) details += `🧩 **Workstream:** ${event.workstream}\n`
    if (event.notes) details += `\n📝 **Notes:**\n${event.notes}`
    return details.trim()
  }
  const handleFormSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    // This explicitly prevents the browser's default GET request
    e.preventDefault();
    
    // Call your existing logic
    handleSubmit(input);
  };
  const handleSubmit = async (userInput: string) => {
    if (!userInput.trim() || isLoading) return

    addMessage("user", userInput)
    setInput("")
    setIsLoading(true)

    try {
      const response = await fetch('/api/query', {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ flow: "events", query: userInput }),
      })

      if (!response.ok) throw new Error((await response.json()).detail || "An error occurred.")
      const result = await response.json()
      const data: Event[] = result.data

      if (!data || data.length === 0) {
        addMessage("bot", `I couldn't find any results. Please try another query.`, {
          showInput: true,
          placeholder: "Try another query...",
        })
      } else if (data.length === 1) {
        addMessage("bot", formatEventDetails(data[0]), { showBackToHome: true })
        setCurrentFlow("home")
      } else {
        setEventList(data)
        let eventsText = "Here's what I found:\n\n"
        data.forEach((event) => {
          const { date } = formatDate(event.start_time)
          eventsText += `- **${event.name}** at ${event.linked_space || "N/A"} on **${date}**\n`
        })
        addMessage("bot", eventsText)
        setTimeout(
          () =>
            addMessage("bot", "Would you like to deep dive into any of these?", {
              showYesNo: true,
              showInput: false,
            }),
          500,
        )
      }
    } catch (error) {
      addMessage("bot", `Sorry, an error occurred. Please try again.`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleYesNoSelect = (choice: "yes" | "no") => {
    if (choice === "yes") {
      addMessage("user", "Yes")
      addMessage("bot", "Please select the specific event you're interested in:", {
        eventOptions: eventList,
        showInput: false,
      })
    } else {
      addMessage("user", "No")
      addMessage("bot", "Alright. You can start a new search.", { showBackToHome: true })
      setCurrentFlow("home")
    }
  }

  const handleEventSelection = async (event: Event) => {
    const { date } = formatDate(event.start_time)
    const selectionText = `${event.name} on ${date}`
    addMessage("user", selectionText)
    setIsLoading(true)

    try {
      const response = await fetch(`/api/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ flow: "get_event_details", query: selectionText }),
      })

      if (!response.ok) throw new Error((await response.json()).detail || "An error occurred.")
      const result = await response.json()

      if (result.data && result.data.length > 0) {
        addMessage("bot", formatEventDetails(result.data[0]), { showBackToHome: true })
      } else {
        addMessage("bot", "Sorry, I couldn't retrieve the details for that specific event.")
      }
    } catch (error) {
      addMessage("bot", "An error occurred while fetching details.")
    } finally {
      setIsLoading(false)
      setCurrentFlow("home")
    }
  }

  const handleBackToHome = () => {
    setCurrentFlow("home")
    setShowChat(false)
    setMessages([])
  }

  const formatMessage = (content: string) =>
    content.split("\n").map((line, index) => (
      <p key={index} className="mb-1">
        {line
          .split(/(\*\*.*?\*\*)/g)
          .filter(Boolean)
          .map((part, i) =>
            part.startsWith("**") ? (
              <strong key={i} className="font-semibold text-gray-900">
                {part.slice(2, -2)}
              </strong>
            ) : (
              part
            ),
          )}
      </p>
    ))

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50/30 to-indigo-50/50">
      {/* Subtle background pattern */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(99,102,241,0.05)_1px,transparent_0)] [background-size:20px_20px]" />

      <div className="relative flex flex-col h-screen max-w-7xl mx-auto">
        {/* Header */}
        <motion.header
          initial={{ y: -20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          className="bg-white/80 backdrop-blur-xl border-b border-gray-200/60 px-6 py-5"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="relative">
                <div className="w-12 h-12 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-500/25">
                  <Calendar className="h-6 w-6 text-white" />
                </div>
                <div className="absolute -top-1 -right-1 w-4 h-4 bg-emerald-400 rounded-full border-2 border-white" />
              </div>
              <div>
                <h1 className="text-xl font-semibold text-gray-900">Festival Events Assistant</h1>
                <p className="text-sm text-gray-600">Discover events with intelligent search</p>
              </div>
            </div>

            {showChat && (
              <motion.button
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                onClick={handleBackToHome}
                className="flex items-center gap-2 px-4 py-2.5 text-gray-600 hover:text-gray-900 bg-gray-100/60 hover:bg-gray-200/60 rounded-xl transition-all duration-200 backdrop-blur-sm"
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </motion.button>
            )}
          </div>
        </motion.header>

        {/* Main Content */}
        <main className="flex-1 overflow-hidden">
          <AnimatePresence mode="wait">
            {!showChat ? (
              <motion.div
                key="home"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4, ease: "easeOut" }}
                className="flex items-center justify-center h-full p-8"
              >
                <div className="text-center max-w-5xl mx-auto">
                  <motion.div
                    initial={{ scale: 0.9, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ delay: 0.2, duration: 0.5 }}
                    className="mb-12"
                  >
                    <div className="relative inline-block mb-8">
                      <div className="w-20 h-20 bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 rounded-2xl flex items-center justify-center shadow-2xl shadow-indigo-500/25">
                        <Sparkles className="h-10 w-10 text-white" />
                      </div>
                      <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ duration: 20, repeat: Number.POSITIVE_INFINITY, ease: "linear" }}
                        className="absolute -inset-3 bg-gradient-to-r from-indigo-500/20 via-purple-500/20 to-pink-500/20 rounded-2xl blur-xl"
                      />
                    </div>

                    <h2 className="text-4xl font-bold text-gray-900 mb-4 bg-gradient-to-r from-gray-900 via-indigo-900 to-purple-900 bg-clip-text text-transparent">
                      How can I help you today?
                    </h2>
                    <p className="text-xl text-gray-600 max-w-2xl mx-auto leading-relaxed">
                      Choose your preferred way to explore events. I'll guide you through finding exactly what you need.
                    </p>
                  </motion.div>

                  <motion.div
                    initial={{ opacity: 0, y: 30 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.4, duration: 0.6 }}
                    className="grid md:grid-cols-3 gap-8"
                  >
                    {[
                      {
                        title: "Search Events",
                        icon: Search,
                        description: "Find specific events by name, keyword, or theme",
                        category: "Events" as const,
                        color: "from-blue-500 to-cyan-500",
                        bgColor: "from-blue-50 to-cyan-50",
                      },
                      {
                        title: "Browse Locations",
                        icon: MapPin,
                        description: "Discover what's happening at venues and spaces",
                        category: "Location" as const,
                        color: "from-emerald-500 to-teal-500",
                        bgColor: "from-emerald-50 to-teal-50",
                      },
                      {
                        title: "Check Dates",
                        icon: CalendarDays,
                        description: "View all events scheduled for specific dates",
                        category: "Date" as const,
                        color: "from-purple-500 to-pink-500",
                        bgColor: "from-purple-50 to-pink-50",
                      },
                    ].map((card, index) => (
                      <motion.button
                        key={card.title}
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.6 + index * 0.1, duration: 0.5 }}
                        whileHover={{ y: -4, scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => handleCategorySelect(card.category)}
                        className="group relative bg-white/70 backdrop-blur-sm rounded-2xl p-8 border border-gray-200/60 hover:border-gray-300/60 shadow-lg shadow-gray-900/5 hover:shadow-xl hover:shadow-gray-900/10 transition-all duration-300 text-left overflow-hidden"
                      >
                        <div
                          className={`absolute inset-0 bg-gradient-to-br ${card.bgColor} opacity-0 group-hover:opacity-50 transition-opacity duration-300`}
                        />

                        <div className="relative z-10">
                          <div
                            className={`w-14 h-14 bg-gradient-to-br ${card.color} rounded-xl flex items-center justify-center mb-6 shadow-lg group-hover:scale-110 transition-transform duration-300`}
                          >
                            <card.icon className="h-7 w-7 text-white" />
                          </div>

                          <h3 className="text-xl font-semibold text-gray-900 mb-3 group-hover:text-gray-800 transition-colors">
                            {card.title}
                          </h3>

                          <p className="text-gray-600 leading-relaxed group-hover:text-gray-700 transition-colors">
                            {card.description}
                          </p>
                        </div>
                      </motion.button>
                    ))}
                  </motion.div>
                </div>
              </motion.div>
            ) : (
              <motion.div
                key="chat"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}
                className="flex flex-col h-full"
              >
                {/* Chat Messages */}
                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                  <AnimatePresence>
                    {messages.map((msg, index) => (
                      <motion.div
                        key={index}
                        initial={{ opacity: 0, y: 15, scale: 0.95 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        transition={{ duration: 0.3, ease: "easeOut" }}
                        className={`flex gap-4 ${msg.type === "user" ? "justify-end" : "justify-start"}`}
                      >
                        {msg.type === "bot" && (
                          <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center flex-shrink-0 shadow-lg shadow-indigo-500/25">
                            <Bot className="h-5 w-5 text-white" />
                          </div>
                        )}

                        <div className={`max-w-2xl ${msg.type === "user" ? "order-first" : ""}`}>
                          <motion.div
                            whileHover={{ scale: 1.01 }}
                            className={`px-5 py-4 rounded-2xl shadow-lg ${
                              msg.type === "user"
                                ? "bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-indigo-500/25"
                                : "bg-white/80 backdrop-blur-sm border border-gray-200/60 text-gray-900 shadow-gray-900/5"
                            }`}
                          >
                            <div className="text-sm leading-relaxed">{formatMessage(msg.content)}</div>

                            {/* Event Options */}
                            {msg.eventOptions && !isLoading && (
                              <motion.div
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="mt-4 space-y-3"
                              >
                                {msg.eventOptions.map((event, eventIndex) => {
                                  const { date } = formatDate(event.start_time)
                                  return (
                                    <motion.button
                                      key={event.airtable_id}
                                      initial={{ opacity: 0, x: -10 }}
                                      animate={{ opacity: 1, x: 0 }}
                                      transition={{ delay: eventIndex * 0.1 }}
                                      whileHover={{ scale: 1.02, x: 4 }}
                                      whileTap={{ scale: 0.98 }}
                                      onClick={() => handleEventSelection(event)}
                                      className="w-full text-left bg-gray-50/80 hover:bg-gray-100/80 backdrop-blur-sm p-4 rounded-xl transition-all duration-200 border border-gray-200/60 hover:border-gray-300/60 hover:shadow-md"
                                    >
                                      <div className="font-medium text-gray-900 text-sm">{event.name}</div>
                                      <div className="text-gray-600 text-xs mt-1">{date}</div>
                                    </motion.button>
                                  )
                                })}
                              </motion.div>
                            )}

                            {/* Yes/No Buttons */}
                            {msg.showYesNo && !isLoading && (
                              <motion.div
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="mt-4 flex gap-3"
                              >
                                <motion.button
                                  whileHover={{ scale: 1.02 }}
                                  whileTap={{ scale: 0.98 }}
                                  onClick={() => handleYesNoSelect("yes")}
                                  className="flex-1 py-3 px-4 bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 text-white text-sm font-medium rounded-xl transition-all duration-200 shadow-lg shadow-emerald-500/25"
                                >
                                  Yes, show me
                                </motion.button>
                                <motion.button
                                  whileHover={{ scale: 1.02 }}
                                  whileTap={{ scale: 0.98 }}
                                  onClick={() => handleYesNoSelect("no")}
                                  className="flex-1 py-3 px-4 bg-gray-100/80 hover:bg-gray-200/80 text-gray-700 text-sm font-medium rounded-xl transition-all duration-200 backdrop-blur-sm"
                                >
                                  No, thanks
                                </motion.button>
                              </motion.div>
                            )}

                            {/* Back to Home Button */}
                            {msg.showBackToHome && !isLoading && (
                              <motion.div
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="mt-4"
                              >
                                <motion.button
                                  whileHover={{ scale: 1.02 }}
                                  whileTap={{ scale: 0.98 }}
                                  onClick={handleBackToHome}
                                  className="w-full py-3 px-4 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white text-sm font-medium rounded-xl transition-all duration-200 shadow-lg shadow-indigo-500/25"
                                >
                                  Start New Search
                                </motion.button>
                              </motion.div>
                            )}
                          </motion.div>
                        </div>

                        {msg.type === "user" && (
                          <div className="w-10 h-10 bg-gradient-to-br from-gray-600 to-gray-700 rounded-xl flex items-center justify-center flex-shrink-0 shadow-lg">
                            <User className="h-5 w-5 text-white" />
                          </div>
                        )}
                      </motion.div>
                    ))}
                  </AnimatePresence>

                  {/* Loading Animation */}
                  {isLoading && (
                    <motion.div
                      initial={{ opacity: 0, y: 15 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="flex gap-4 justify-start"
                    >
                      <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center flex-shrink-0 shadow-lg shadow-indigo-500/25">
                        <Bot className="h-5 w-5 text-white" />
                      </div>
                      <div className="bg-white/80 backdrop-blur-sm border border-gray-200/60 px-5 py-4 rounded-2xl shadow-lg shadow-gray-900/5">
                        <div className="flex items-center gap-2">
                          {[0, 1, 2].map((i) => (
                            <motion.div
                              key={i}
                              className="w-2 h-2 bg-indigo-400 rounded-full"
                              animate={{
                                scale: [1, 1.2, 1],
                                opacity: [0.5, 1, 0.5],
                              }}
                              transition={{
                                duration: 1.2,
                                repeat: Number.POSITIVE_INFINITY,
                                delay: i * 0.2,
                              }}
                            />
                          ))}
                        </div>
                      </div>
                    </motion.div>
                  )}

                  <div ref={messagesEndRef} />
                </div>

                {/* Input Area */}
                {messages.at(-1)?.showInput && (
                  <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="border-t border-gray-200/60 bg-white/60 backdrop-blur-xl p-6"
                  >
                    <form
                      onSubmit={handleFormSubmit}
                      className="flex gap-4 max-w-4xl mx-auto"
                    >
                      <div className="flex-1 relative">
                        <input
                          type="text"
                          value={input}
                          onChange={(e) => setInput(e.target.value)}
                          placeholder={messages.at(-1)?.placeholder || "Type your message..."}
                          className="w-full px-5 py-4 bg-white/80 backdrop-blur-sm border border-gray-300/60 rounded-2xl focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50 transition-all duration-200 shadow-lg shadow-gray-900/5 placeholder-gray-500"
                          disabled={isLoading}
                          autoFocus
                        />
                      </div>
                      <motion.button
                        type="submit"
                        disabled={isLoading || !input.trim()}
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        className="px-6 py-4 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 disabled:from-gray-400 disabled:to-gray-500 text-white font-medium rounded-2xl transition-all duration-200 shadow-lg shadow-indigo-500/25 disabled:cursor-not-allowed disabled:shadow-none"
                      >
                        <Send className="h-5 w-5" />
                      </motion.button>
                    </form>
                  </motion.div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </main>
      </div>
    </div>
  )
}
