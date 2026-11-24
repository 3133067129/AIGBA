sched = {}
pending = ""
client = nil

function onframe()
  local f = emu:currentFrame()
  local a = sched[f]
  if a then
    sched[f] = nil
    for i = 1, #a do
      emu:setKeys(a[i])
    end
  end
end

function process(line)
  local cmd, a, b = line:match("^(%S+)%s*(%S*)%s*(%S*)")
  if cmd == "S" then
    local f = tonumber(a)
    local m = tonumber(b)
    if f ~= nil and m ~= nil then
      local l = sched[f]
      if not l then
        l = {}
        sched[f] = l
      end
      l[#l + 1] = m
    end
  elseif cmd == "F" then
    if client then
      client:send("F " .. emu:currentFrame() .. "\n")
    end
  elseif cmd == "R" then
    if client then
      client:send("R " .. a .. " " .. emu:read16(tonumber(a)) .. "\n")
    end
  elseif cmd == "P" then
    if client then
      client:send("P ok\n")
    end
  end
end

function onrecv(sock)
  while true do
    local p, err = sock:receive(1024)
    if p then
      pending = pending .. p
      while true do
        local nl = pending:find("\n")
        if not nl then
          break
        end
        local line = pending:sub(1, nl - 1)
        pending = pending:sub(nl + 1)
        line = line:match("^%s*(.-)%s*$")
        if line ~= "" then
          pcall(process, line)
        end
      end
    else
      if err ~= socket.ERRORS.AGAIN then
        sock:close()
        if client == sock then
          client = nil
        end
      end
      return
    end
  end
end

function onaccept()
  local s, err = server:accept()
  if not err and s then
    if client then
      pcall(function()
        client:close()
      end)
    end
    client = s
    s:add("received", onrecv)
    s:add("error", function(x)
      x:close()
      if client == x then
        client = nil
      end
    end)
  end
end

if not sched_server_running then
  sched_server_running = true
  callbacks:add("frame", onframe)
  local s, err = socket.bind(nil, 8890)
  if s then
    server = s
    s:listen()
    s:add("received", onaccept)
  end
end
