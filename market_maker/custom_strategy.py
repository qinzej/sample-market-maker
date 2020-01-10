import sys

from market_maker.market_maker import OrderManager

from market_maker.utils import log, constants, errors, math
from market_maker.settings import settings


#
# Helpers
#
logger = log.setup_custom_logger('xxx')


class CustomOrderManager(OrderManager):
    """A sample order manager for implementing your own custom strategy"""
    def get_ticker(self):
        ticker = self.exchange.get_ticker()
        tickLog = self.exchange.get_instrument()['tickLog']

        # Set up our buy & sell positions as the smallest possible unit above and below the current spread
        # and we'll work out from there. That way we always have the best price but we don't kill wide
        # and potentially profitable spreads.
        self.start_position_buy = ticker["buy"] + self.instrument['tickSize']
        self.start_position_sell = ticker["sell"]

        # If we're maintaining spreads and we already have orders in place,
        # make sure they're not ours. If they are, we need to adjust, otherwise we'll
        # just work the orders inward until they collide.
        if settings.MAINTAIN_SPREADS:
            if ticker['buy'] == self.exchange.get_highest_buy()['price']:
                self.start_position_buy = ticker["buy"]
            if ticker['sell'] == self.exchange.get_lowest_sell()['price']:
                self.start_position_sell = ticker["sell"]

        # Back off if our spread is too small.
        if self.start_position_buy >= self.start_position_sell:
            self.start_position_buy -= self.instrument['tickSize']
            # self.start_position_sell += self.instrument['tickSize'] * settings.ORDER_PAIRS / 2

        # Midpoint, used for simpler order placement.
        self.start_position_mid = ticker["mid"]
        logger.info(
            "%s Ticker: Buy: %.*f, Sell: %.*f, tickSize: %.*f" %
            (self.instrument['symbol'], tickLog, ticker["buy"], tickLog, ticker["sell"],
             tickLog, self.instrument['tickSize'])
        )
        logger.info('Start Positions: Buy: %.*f, Sell: %.*f, Mid: %.*f' %
                    (tickLog, self.start_position_buy, tickLog, self.start_position_sell,
                     tickLog, self.start_position_mid))
        return ticker

    def get_price_offset(self, index):
        """Given an index (1, -1, 2, -2, etc.) return the price for that side of the book.
           Negative is a buy, positive is a sell."""

        tickSize = self.instrument['tickSize']

        # Maintain existing spreads for max profit
        if settings.MAINTAIN_SPREADS:
            start_position = self.start_position_buy if index < 0 else self.start_position_sell
            # First positions (index 1, -1) should start right at start_position, others should branch from there
            index = index + 1 if index < 0 else index - 1
        else:
            # Offset mode: ticker comes from a reference exchange and we define an offset.
            start_position = self.start_position_buy if index < 0 else self.start_position_sell

            # If we're attempting to sell, but our sell price is actually lower than the buy,
            # move over to the sell side.
            if index > 0 and start_position < self.start_position_buy:
                start_position = self.start_position_sell
            # Same for buys.
            if index < 0 and start_position > self.start_position_sell:
                start_position = self.start_position_buy

        return math.toNearest((start_position + 4 * tickSize * index), self.instrument['tickSize'])

    def converge_orders(self, buy_orders, sell_orders):
        """Converge the orders we currently have in the book with what we want to be in the book.
           This involves amending any open orders and creating new ones if any have filled completely.
           We start from the closest orders outward."""

        tickLog = self.exchange.get_instrument()['tickLog']
        to_amend = []
        to_create = []
        to_cancel = []
        buys_matched = 0
        sells_matched = 0
        existing_orders = self.exchange.get_orders()

        for order in existing_orders:
            logger.info("%4s %d @ %.*f" % (order['side'], order['orderQty'], tickLog, order['price']))
            try:
                if order['side'] == 'Buy':
                    buys_matched += 1
                else:
                    sells_matched += 1

            except IndexError:
                # Will throw if there isn't a desired order to match. In that case, cancel it.
                to_cancel.append(order)

        logger.info("existing_orders len %d " % (len(existing_orders)))
        new_order_index = min((settings.ORDER_PAIRS-buys_matched), (settings.ORDER_PAIRS-sells_matched))

        while new_order_index > 0:
            index = settings.ORDER_PAIRS - new_order_index
            logger.info("order index %d " % index)
            to_create.append(buy_orders[index])
            to_create.append(sell_orders[index])
            new_order_index -= 1
        # if buys_matched == sells_matched:
        #     while buys_matched < len(buy_orders):
        #         to_create.append(buy_orders[buys_matched])
        #         buys_matched += 1
        #
        #     while sells_matched < len(sell_orders):
        #         to_create.append(sell_orders[sells_matched])
        #         sells_matched += 1

        if len(to_create) > 0:
            logger.info("Creating %d orders:" % (len(to_create)))
            for order in reversed(to_create):
                logger.info("%4s %d @ %.*f" % (order['side'], order['orderQty'], tickLog, order['price']))
            self.exchange.create_bulk_orders(to_create)


def run():
    logger.info('BitMEX Market custom strategy \n')
    order_manager = CustomOrderManager()

    # Try/except just keeps ctrl-c from printing an ugly stacktrace
    try:
        order_manager.run_loop()
    except (KeyboardInterrupt, SystemExit):
        sys.exit()
