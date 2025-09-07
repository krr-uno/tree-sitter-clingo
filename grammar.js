

// module.exports = grammar({
//     name: 'clingo',

//     word: $ => $.identifier,

//     rules: {
//         source_file: $ => seq(
//             $.rule,
//             $.condition
//           ),

//         rule: $ => seq("ab", "p"),

//         condition: $ => seq("a", $.name),

//         name: $ => token(/b[ ]*[pq]/),

//         identifier: $ => token(choice(
//             "p",
//             "ab",
//             "a",
//         )),
//     }
// });


module.exports = grammar({
    name: 'clingo',

    word: $ => $.identifier,

    rules: {
        source_file: $ => seq(
            $.rule,
            $.condition
          ),

        rule: $ => seq(":b", "p"),

        condition: $ => seq(":", $.name),

        name: $ => token(/b[ ]*[pq]/),

        identifier: $ => token(choice(
            "p",
            ":b",
        )),
    }
});