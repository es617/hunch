# hunch.zsh — on-device LLM shell hooks
#
# Source from ~/.zshrc:  source /path/to/hunch.zsh
# Or install via plugin manager with this repo URL.
#
# Hooks:
#   Ctrl+G .... natural language → shell command (inspect before running)
#   typo ...... command_not_found_handler suggests corrections
#   failure ... TRAPZERR explains what went wrong
#
# Requires: macOS 26 Tahoe, Apple Intelligence enabled, hunch installed.

# Bail early if hunch isn't installed
(( $+commands[hunch] )) || return 0

# ---------------------------------------------------------------------------
# 1. Ctrl+G — natural language to shell command
# ---------------------------------------------------------------------------
hunch-cmd() {
  local prompt="${BUFFER}"
  [[ -z "$prompt" ]] && return

  zle -R "hunch: thinking..."

  local -a hunch_args
  [[ -n "$HUNCH_TEMPERATURE" ]] && hunch_args+=(--temperature "$HUNCH_TEMPERATURE")
  [[ -n "$HUNCH_SAMPLES" ]] && hunch_args+=(--samples "$HUNCH_SAMPLES")

  local cmd
  cmd=$(hunch "${hunch_args[@]}" "$prompt" 2>/dev/null)

  if [[ -n "$cmd" ]]; then
    BUFFER="$cmd"
    CURSOR=${#BUFFER}
  fi
  zle redisplay
}
zle -N hunch-cmd
bindkey '^G' hunch-cmd

# ---------------------------------------------------------------------------
# 2. command_not_found_handler — smart typo/platform correction
# ---------------------------------------------------------------------------
command_not_found_handler() {
  # Prevent infinite recursion if hunch is not in PATH
  (( $+commands[hunch] )) || { echo "zsh: command not found: $1"; return 127; }

  local result
  result=$(hunch --notfound "$*" 2>/dev/null)

  if [[ -z "$result" ]]; then
    echo "zsh: command not found: $1"
  elif [[ "$result" == install:* ]]; then
    print -P "%F{8}not installed:%f ${result#install: }"
  elif [[ "$result" == typo:* ]]; then
    print -P "%F{8}did you mean:%f ${result#typo: }"
  elif [[ "$result" == macos:* ]]; then
    print -P "%F{8}macOS equivalent:%f ${result#macos: }"
  else
    # Fallback: model didn't follow format
    print -P "%F{8}did you mean:%f $result"
  fi
  return 127
}

# ---------------------------------------------------------------------------
# 3. TRAPZERR — explain failures after non-zero exit
# ---------------------------------------------------------------------------
typeset -g _hunch_last_cmd=""
__hunch_preexec() { _hunch_last_cmd="$1"; }
autoload -Uz add-zsh-hook
add-zsh-hook preexec __hunch_preexec

TRAPZERR() {
  local exit_code=$?

  [[ -o interactive ]] || return
  (( ${#funcstack} > 1 )) && return

  local last_cmd="$_hunch_last_cmd"
  [[ -z "$last_cmd" ]] && return

  (( exit_code > 128 )) && return
  (( exit_code == 127 )) && return
  (( exit_code == 1 )) && return

  local skip_cmds=(grep egrep fgrep rg ag diff test "[" "[[" ps lsof)
  local stripped="${last_cmd#sudo }"
  stripped="${stripped#env }"
  stripped="${stripped#command }"
  local first_word="${stripped%% *}"
  for skip in "${skip_cmds[@]}"; do
    [[ "$first_word" == "$skip" ]] && return
  done

  (( ${#last_cmd} < 3 )) && return

  # Don't send commands that might contain secrets to the model
  [[ "${last_cmd:l}" =~ (password|passwd|token|secret|bearer|api[_-]?key|auth|credential) ]] && return

  local explanation
  explanation=$(hunch --explain "Command: $last_cmd — Exit code: $exit_code" 2>/dev/null)

  [[ -n "$explanation" ]] && print -P "%F{8}${explanation}%f"
}
