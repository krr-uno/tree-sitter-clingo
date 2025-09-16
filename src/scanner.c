#include "tree_sitter/parser.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum TokenType {
    COLON_DASH,
    COLON,
};

typedef enum {
    START,
    COLON_SEEN,
} State;

typedef enum {
    CONTINUE,
    RETURN_TOKEN,
    FAIL,
} Action;

#define EXECUTE(action) do{\
    Action result = (action);\
    if (result == RETURN_TOKEN) {\
        return true;\
    } else if (result == FAIL) {\
        return false;\
    }\
} while(false); continue

static inline void advance(TSLexer *lexer) { lexer->advance(lexer, false); }

static inline void skip(TSLexer *lexer) { lexer->advance(lexer, true); }

static inline void skip_blanks(TSLexer *lexer) {
    while (!lexer->eof(lexer) && (lexer->lookahead == ' ' || ('\t' <= lexer->lookahead && lexer->lookahead <= '\r'))) {
        skip(lexer);
    }
}

static inline Action state_start(TSLexer *lexer, const bool *valid_symbols, State *state) {
    skip_blanks(lexer);
    if (lexer->lookahead == ':') {
        *state = COLON_SEEN;
        advance(lexer);
        return CONTINUE;
    }
    return FAIL;
}

static inline Action state_colon_seen(TSLexer *lexer, const bool *valid_symbols, State *state) {
    if (lexer->lookahead == '-') {
        lexer->result_symbol = COLON_DASH;
        advance(lexer);
        return RETURN_TOKEN;
    }
    if (valid_symbols[COLON]) {
            lexer->result_symbol = COLON;
            return RETURN_TOKEN;
    }
    return FAIL;
}

bool tree_sitter_clingo_external_scanner_scan(void *payload, TSLexer *lexer, const bool *valid_symbols) {
    State state = START;
    do{
        if (lexer->eof(lexer)) return false;
        switch (state)
        {
        case START:
            EXECUTE(state_start(lexer, valid_symbols, &state));
        case COLON_SEEN:
            EXECUTE(state_colon_seen(lexer, valid_symbols, &state));
        default:
            return false;
        }
    }
    while(true);
}

unsigned tree_sitter_clingo_external_scanner_serialize(void *payload, char *buffer) {
    return 0;
}

void tree_sitter_clingo_external_scanner_deserialize(void *payload, const char *buffer, unsigned length) {
    return;
}

void *tree_sitter_clingo_external_scanner_create() {

    return NULL;
}

void tree_sitter_clingo_external_scanner_destroy(void *payload) {
    return;
}
